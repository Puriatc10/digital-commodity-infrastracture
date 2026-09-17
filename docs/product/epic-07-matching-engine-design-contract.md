# Epic 7 — Matching Engine

## Design Contract, Owner Policies, Architectural Invariants & Review Requirements

این سند قرارداد طراحی اپیک ۷ است و باید پیش از شروع پیاده‌سازی تسک‌های این اپیک، منبع حقیقت فنی و محصولی آن در کنار Product Specification، Roadmap، ADRها و قرارداد طراحی اپیک ۳ باشد.

هدف سند این است که پیش از نوشتن کد دقیقاً مشخص کند:

- Matching در نسخه اول چه مسئله‌ای را حل می‌کند؛
- Target و Candidate دقیقاً چه هستند؛
- Candidate Discovery با Eligibility و Scoring چه تفاوتی دارد؛
- قواعد Hard و Soft چگونه جدا می‌شوند؛
- مقدار Unknown چگونه از Mismatch تفکیک می‌شود؛
- Dynamic Specification چگونه بدون hard-code شدن Commodity مقایسه می‌شود؛
- Cross-Schema Matching چگونه معنای تاریخی را حفظ می‌کند؛
- Verification، Geography، Quantity، Availability و History چگونه وارد نتیجه می‌شوند؛
- Broker چرا lane مستقل دارد؛
- Buyer و Operator چه چیزهایی را می‌توانند ببینند؛
- نتیجه Matching چگونه versioned، persisted، deterministic و explainable می‌ماند؛
- چه چیزهایی عمداً در Epic 7 ساخته نمی‌شوند؛
- و در Review Gate چه مواردی باید به‌صورت اجرایی اثبات شوند.

---

# 1. Epic Objective

هدف Epic 7 ساخت یک موتور deterministic، explainable و قابل audit برای کشف و رتبه‌بندی مسیرهای محتمل تأمین برای یک RFQ است.

خروجی موتور نباید به معنی انتخاب Supplier نهایی یا recommendation خرید باشد.

مسئله‌ای که این اپیک حل می‌کند:

```text
RFQ
  ↓
Authorized Candidate Discovery
  ↓
Eligibility Filtering
  ↓
Compatibility Evaluation
  ↓
Lane-specific Scoring
  ↓
Explainable Ranked Results
  ↓
Human Selection / Follow-up Action
```

سؤال اصلی Epic 7:

> «برای این RFQ با چه supply، supplier یا brokerهایی ارزش دارد وارد procurement conversation شویم؟»

سؤال زیر متعلق به Epic 8 است و در این اپیک پاسخ داده نمی‌شود:

> «از Offerهای واقعی دریافت‌شده کدام Offer بهترین تصمیم تجاری است؟»

---

# 2. Roadmap Contract

Roadmap برای Epic 7 این capabilityها را الزام می‌کند:

```text
T0701 — Matching Candidate Model
T0702 — Core Matching Rules
T0703 — Dynamic Specification Matching
T0704 — Trust / Verification Signals
T0705 — Historical Signals
T0706 — Opportunity Sources
T0707 — Explainable Scoring
T0708 — Matching UI
```

Candidate universe باید بتواند این منابع را ببیند:

```text
Organizations
Supply Listings
Qualified Opportunities
Brokers
```

Core matching حداقل باید این ابعاد را در نظر بگیرد:

```text
commodity
organization capability
geography
availability
```

Specification matching باید کاملاً generic باشد و هیچ Bitumen-specific branch در engine وجود نداشته باشد.

---

# 3. Relationship With Epic 3

Epic 3 این invariant را ایجاد کرده است:

```text
Business Record
  → CommodityDefinition
  → CommoditySchemaVersion
  → specifications JSONB
```

هر record باید schema version زمان خودش را نگه دارد و historical interpretation نباید با active schema امروز انجام شود.

Epic 3 عمداً موارد زیر را وارد Commodity Definition نکرد:

```text
matching_score
matching_algorithm
attribute_weight
tolerance_scoring
supplier ranking
AI matching
```

این موارد متعلق به Epic 7 هستند.

نتیجه مهم:

> Commodity Schema تعریف می‌کند یک attribute چیست؛ Matching Policy تعریف می‌کند آن attribute چگونه با demand مقایسه شود.

این دو concern نباید با هم ادغام شوند.

---

# 4. Owner-approved v1 Policies

هشت policy زیر برای نسخه اول قطعی هستند.

## 4.1 Matching Target

فقط RFQ می‌تواند Matching Target باشد.

```text
Matching Target v1 = RFQ only
```

Qualified Demand Opportunity مستقیماً target نیست.

Flow صحیح:

```text
Demand Opportunity
  → Qualification
  → RFQ Conversion
  → RFQ
  → Matching
```

این تصمیم مانع اضافه شدن Demand Opportunity به‌عنوان target در نسخه بعدی نیست، ولی v1 نباید abstraction عمومی و بدون نیاز واقعی برای MatchTarget ایجاد کند.

## 4.2 Geography

Geography فقط در صورت نقض constraint صریح، Hard Failure است.

```text
Explicit mandatory geography violation
→ INELIGIBLE
```

در غیر این صورت geography یک signal نرم یا Unknown است.

نباید از country/destination به‌تنهایی logistics intelligence جعلی استخراج شود.

## 4.3 Partial Quantity

کمتر بودن مقدار موجود از مقدار RFQ به‌صورت پیش‌فرض Candidate را حذف نمی‌کند.

```text
Partial quantity
→ eligible + partial score
```

فقط اگر policy صریحاً full fulfilment را الزامی کرده باشد، مقدار ناکافی Hard Failure می‌شود.

## 4.4 Direct Supply Initial Weights

وزن اولیه lane تأمین مستقیم:

```text
Specification compatibility     45
Quantity                         10
Availability                     15
Geography                        10
Trust / Verification             15
Historical Signals                5
                                 ---
                                 100
```

در سطح محصول می‌توان Quantity + Availability را یک بلوک 25 درصدی در نظر گرفت؛ در محاسبه v1 این بلوک به 10 و 15 تفکیک می‌شود.

## 4.5 Verification

Policy اولیه:

```text
Verified               → 1.00
Basic Verified         → 0.70
Under Review           → 0.30
Documents Submitted    → 0.15
Unverified             → 0.00
Suspended              → HARD EXCLUDE
```

برای ExternalCounterparty که verification platform-level ندارد:

```text
Trust = UNKNOWN
```

نباید ExternalCounterparty را به‌صورت خودکار معادل Unverified Organization در نظر گرفت.

## 4.6 Buyer Visibility

Qualified External Opportunity یک internal operational object است.

Buyer نباید اطلاعات داخلی آن را از Matching ببیند.

```text
Operator / Product Admin
→ may see Qualified Supply Opportunities

Buyer
→ does not receive Qualified Opportunity candidates
```

Buyer فقط پس از تبدیل آن lead به یک artifact مناسب Buyer مانند Supply Listing یا Offer می‌تواند با آن supply وارد flow شود.

## 4.7 Cross-schema Matching

Cross-schema matching فقط بر اساس semantic identity صریح مجاز است.

```text
Same key
≠ Same meaning
```

مقایسه attributeهای دو schema version فقط زمانی مجاز است که semantic fingerprint یکسان و semantics سازگار داشته باشند.

## 4.8 Broker Ranking

Broker در lane جدا از Direct Supply رتبه‌بندی می‌شود.

```text
Direct Supply Score
≠ Broker Relevance Score
```

این دو score هرگز در یک ranking مشترک قرار نمی‌گیرند.

---

# 5. Core Architectural Principle

Matching Engine باید از پنج مرحله مستقل تشکیل شود:

```text
1. Candidate Discovery
2. Eligibility Filtering
3. Compatibility Evaluation
4. Scoring
5. Explanation + Persistence
```

هر مرحله باید contract روشن داشته باشد.

نباید یک service بزرگ تمام query، permission، rule evaluation، scoring و serialization را هم‌زمان انجام دهد.

---

# 6. Matching Target v1

تنها target نسخه اول:

```text
RFQ
```

برای تولید MatchingRun، RFQ باید حداقل:

- متعلق به یک Buyer Organization معتبر باشد؛
- Commodity و exact Schema Version داشته باشد؛
- در lifecycle مناسب matching باشد؛
- از دید actor درخواست‌کننده قابل مدیریت باشد.

Default v1:

```text
RFQ status required for a new MatchingRun:
Published
```

Draft RFQ هنوز demand authoritative محسوب نمی‌شود.

اگر Epic 8 بعداً statusهای عملیاتی دیگری را فعال کرد، گسترش target-state policy باید versioned و explicit باشد.

---

# 7. Matching Is Side-effect Free

اجرای Matching نباید هیچ business workflow دیگری را mutate کند.

Matching نباید:

- RFQ را تغییر دهد؛
- Opportunity را تغییر lifecycle دهد؛
- RFQInvitation بسازد؛
- Broker را assign کند؛
- Offer بسازد؛
- Supply Listing را تغییر دهد؛
- verification را تغییر دهد.

Flow مجاز:

```text
Read
→ Evaluate
→ Persist immutable analytical result
```

Actionهای بعدی user باید از serviceهای domain مربوطه استفاده کنند.

مثلاً:

```text
Invite Supplier
→ existing RFQ Invitation Service
```

نه Matching Service.

---

# 8. Candidate Lanes

نسخه اول سه lane مستقل دارد.

```text
DIRECT_SUPPLY
POTENTIAL_SUPPLIER
BROKER_PATH
```

## 8.1 Direct Supply

منابع:

```text
SupplyListing
Qualified Supply Opportunity
```

این lane نماینده evidence واقعی یا نسبتاً قوی از supply است.

Qualified Opportunity فقط در Operator/Admin run قابل استفاده است.

## 8.2 Potential Supplier

منبع:

```text
Supplier Organization
```

این lane فقط می‌گوید Organization از نظر commodity/capability/trust مسیر بالقوه مناسبی است.

وجود در این lane به معنی موجود بودن quantity یا availability فعلی نیست.

## 8.3 Broker Path

منبع:

```text
Broker Organization
```

این lane بیان می‌کند Broker ممکن است مسیر مناسبی برای دسترسی به supply باشد.

Broker نباید به‌عنوان Supplier یا inventory holder تفسیر شود.

---

# 9. Candidate Sources Are Evidence, Not One Entity Type

نباید تمام sourceها به یک مفهوم تجاری مصنوعی تبدیل شوند.

مثلاً Supply Listing و Supplier Organization معنای یکسان ندارند.

یک Organization ممکن است هم‌زمان:

```text
Supplier Organization
Supply Listing A
Supply Listing B
Qualified Opportunity
```

داشته باشد.

Engine نباید اینها را blindly deduplicate کند.

هر source یک evidence artifact مستقل است.

UI می‌تواند آنها را بر اساس Organization group کند، ولی persistence باید source identity را حفظ کند.

---

# 10. Candidate Provider Architecture

برای هر source یک provider مستقل وجود دارد.

Conceptual interfaces:

```text
SupplyListingCandidateProvider
SupplyOpportunityCandidateProvider
SupplierOrganizationCandidateProvider
BrokerCandidateProvider
```

Contract مشترک:

```text
find_candidates(context, actor_scope)
→ immutable candidate snapshots
```

Provider مسئول این موارد است:

- query کردن source صحیح؛
- اعمال source lifecycle؛
- اعمال authorization پیش از scoring؛
- ساخت safe snapshot؛
- eager loading لازم؛
- جلوگیری از N+1 واضح.

Provider نباید score نهایی بسازد.

---

# 11. Authorization Before Matching

Security filtering باید قبل از candidate evaluation انجام شود.

صحیح:

```text
Authorized Candidate Universe
→ Matching
```

غلط:

```text
All Internal Data
→ Matching
→ hide some candidates in frontend
```

این قاعده جلوی leakage از طریق موارد زیر را می‌گیرد:

```text
candidate count
ranking
score
explanations
pagination totals
```

---

# 12. Matching Run Audience

هر MatchingRun یک audience صریح دارد.

```text
BUYER
OPERATOR
```

Product Admin از semantics Operator استفاده می‌کند.

Buyer run و Operator run candidate universe متفاوت دارند و نباید همان persisted run بعداً برای audience دیگر re-project شود.

### Buyer Run

می‌تواند از منابع مجاز زیر استفاده کند:

```text
Visible Supply Listings
Safe Supplier Organizations
Safe Broker Organizations
```

نباید Qualified Opportunity داخلی را وارد candidate universe کند.

### Operator Run

می‌تواند علاوه بر منابع بالا، بر اساس Product Role به:

```text
Qualified Supply Opportunities
```

دسترسی داشته باشد.

---

# 13. Matching Result Access Control

Matching result فقط برای actorهای مرتبط با RFQ owner یا Product System Roles مناسب قابل مشاهده است.

Supplier/Brokerی که RFQ را می‌بیند یا به آن invite شده است، حق مشاهده competitor matching results را فقط به دلیل RFQ visibility ندارد.

Backend authorization authoritative است.

Frontend hiding امنیت محسوب نمی‌شود.

---

# 14. Hard Constraint vs Soft Signal

هر rule باید یکی از این دو نوع باشد:

```text
HARD
SOFT
```

## Hard

Explicit failure باعث حذف Candidate می‌شود.

مثال:

```text
wrong commodity
wrong required capability
suspended organization
no availability overlap for authoritative supply
explicit forbidden geography
```

## Soft

Candidate eligible می‌ماند ولی rank تغییر می‌کند.

مثال:

```text
partial quantity
partial availability overlap
non-preferred geography
verification level
historical performance
```

هیچ Hard Failure نباید فقط به یک score پایین تبدیل شود.

---

# 15. Signal Outcome Model

نتیجه هر signal فقط boolean نیست.

Outcomeهای v1:

```text
PASS
PARTIAL
FAIL
UNKNOWN
NOT_APPLICABLE
```

تعریف:

### PASS

داده موجود است و شرط را کامل پاس می‌کند.

### PARTIAL

داده موجود است و compatibility بین صفر و یک دارد.

### FAIL

داده موجود است و incompatibility مشخص است.

اگر rule از نوع Hard باشد:

```text
FAIL → Candidate ineligible
```

### UNKNOWN

داده لازم برای تصمیم وجود ندارد.

Unknown با Fail متفاوت است.

### NOT_APPLICABLE

Signal برای این Candidate یا این Run معنی ندارد.

این outcome نباید coverage را کاهش دهد.

---

# 16. Missing Data Policy

اصل v1:

> Missing evidence به‌صورت پیش‌فرض Unknown است، نه Mismatch.

این تصمیم برای Pilot مهم است، چون بسیاری از Supplier Organizations و External Opportunities اطلاعات کامل نخواهند داشت.

Hard Failure فقط وقتی رخ می‌دهد که incompatibility قابل اثبات باشد یا policy صریحاً evidence اجباری تعریف کند.

---

# 17. Eligibility Rules v1

حداقل Eligibility Gateها:

## Commodity

```text
RFQ.commodity == candidate.commodity
```

Mismatch:

```text
HARD FAIL
```

## Capability

برای Organization candidate:

```text
Supplier lane
→ Supplier capability required

Broker lane
→ Broker capability required
```

Capability یک business eligibility signal است و authorization نیست.

## Organization State

Inactive Organization قابل match نیست.

## Verification Suspension

```text
Suspended
→ HARD FAIL
```

## Source Lifecycle

Supply Listing باید lifecycle قابل استفاده داشته باشد.

Qualified Opportunity باید:

```text
direction = Supply
status = Qualified
```

باشد.

## Self Match

به‌صورت پیش‌فرض Organization مالک RFQ نباید به‌عنوان Supplier/Broker خودش match شود.

Internal transfer use case در scope v1 نیست.

---

# 18. Scoring Principles

Score فقط روی Candidateهای eligible محاسبه می‌شود.

سه عدد مستقل داریم:

```text
Fit Score
Evidence Coverage
Ranking Score
```

نباید یک percentage تنها تمام uncertainty را پنهان کند.

---

# 19. Scoring Formula

برای signalهای soft و applicable:

```text
weight = policy weight
raw_score ∈ [0, 1]
```

تعاریف:

```text
A = sum(applicable weights excluding NOT_APPLICABLE)
K = sum(weights with known raw score)
C = sum(weight × raw_score for known signals)
```

سپس:

```text
Fit Score = 100 × C / K

Evidence Coverage = 100 × K / A

Ranking Score = 100 × C / A
```

در نتیجه:

```text
Ranking Score
=
Fit Score × Evidence Coverage / 100
```

مزیت این formula:

- Unknown به‌صورت مصنوعی 50% یا 100% نمی‌شود؛
- Candidate با evidence کم می‌تواند Fit بالایی داشته باشد ولی Ranking و Coverage پایین‌تری خواهد داشت؛
- uncertainty قابل مشاهده باقی می‌ماند.

اگر هیچ known applicable signal وجود نداشته باشد:

```text
Fit Score = null
Evidence Coverage = 0
Ranking Score = 0
```

---

# 20. Numeric Determinism

محاسبات score باید با Decimal انجام شوند، نه binary float.

Persisted scores باید precision ثابت داشته باشند.

مثلاً:

```text
0.0000 → 100.0000
```

Presentation layer می‌تواند مقدار را به شکل دو رقم اعشار نمایش دهد.

Rounding policy باید deterministic و centralized باشد.

---

# 21. Direct Supply Weights

Policy v1:

```text
Specification     45
Quantity          10
Availability      15
Geography         10
Trust             15
History            5
                 ---
                 100
```

Commodity و Capability داخل این 100 نیستند چون eligibility gate هستند.

---

# 22. Quantity Matching

اگر RFQ و Candidate quantity قابل مقایسه داشته باشند:

```text
coverage_ratio = min(candidate_quantity / requested_quantity, 1)
```

مثال:

```text
RFQ = 500 MT
Candidate = 300 MT

Quantity raw score = 0.60
```

Candidate حذف نمی‌شود.

اگر policy صریحاً full quantity را الزامی کند:

```text
coverage_ratio < 1
→ HARD FAIL
```

## Unit Semantics

Epic 7 Unit Conversion Engine نمی‌سازد.

اگر unitها مستقیم قابل مقایسه نباشند و conversion معتبر وجود نداشته باشد:

```text
Quantity = UNKNOWN
```

نه اینکه conversion حدسی انجام شود.

---

# 23. Availability Matching

برای Direct Supply، اگر RFQ delivery window و Candidate availability هر دو معلوم باشند:

### No overlap

```text
HARD FAIL
```

### Full target coverage

```text
raw score = 1.0
```

### Partial overlap

```text
raw score = overlap_duration / requested_delivery_duration
```

و نتیجه:

```text
PARTIAL
```

اگر یکی از بازه‌ها موجود نباشد:

```text
UNKNOWN
```

Engine نباید تاریخ حدسی تولید کند.

---

# 24. Geography Matching

Geography در v1 logistics engine نیست.

## Hard Geography

فقط constraintهای صریح مانند موارد زیر Hard هستند:

```text
required origin
allowed origin set
excluded origin
explicit operating geography requirement
```

Violation:

```text
HARD FAIL
```

## Soft Geography

Preferenceهای صریح غیرالزامی می‌توانند score تولید کنند.

مثلاً:

```text
preferred origin match
→ 1.0

known preference mismatch
→ 0.0
```

## Unknown Geography

داشتن destination و country supplier به‌تنهایی مجوز ساختن route score یا freight score نیست.

در نبود semantics صریح:

```text
UNKNOWN
```

---

# 25. Trust / Verification Matching

Internal Organization policy:

```text
Verified               1.00
Basic Verified         0.70
Under Review           0.30
Documents Submitted    0.15
Unverified             0.00
Suspended              HARD EXCLUDE
```

ExternalCounterparty:

```text
UNKNOWN
```

Broker attribution یک External Opportunity نباید به‌صورت خودکار جایگزین verification آن Supplier شود.

---

# 26. Historical Signals

Roadmap historical signals را فقط در صورت وجود data واقعی می‌خواهد.

منابع آینده ممکن است شامل موارد زیر شوند:

```text
previous response
previous deal
historical performance
```

Epic 7 نباید fake history تولید کند.

اگر provider واقعی برای یک signal هنوز وجود ندارد:

```text
NOT_APPLICABLE
```

اگر provider وجود دارد ولی برای Candidate داده مشخصی در دسترس نیست:

policy باید بین Unknown و known absence تفاوت قائل شود.

در v1 هیچ synthetic successful-deal signal مجاز نیست.

---

# 27. Historical Provider Interface

Historical logic باید provider-based باشد.

Conceptual:

```text
HistoricalSignalProvider
```

Later implementations می‌توانند بدون تغییر Scoring Engine اضافه شوند:

```text
ResponseHistorySignalProvider
DealHistorySignalProvider
ExecutionPerformanceSignalProvider
```

---

# 28. Dynamic Specification Matching

Specification matching باید کاملاً generic باشد.

ممنوع:

```python
if commodity.code == "bitumen":
    ...
```

ممنوع:

```python
if attribute.key == "softening_point":
    ...
```

در generic engine.

Commodity-specific differences باید از versioned data/policy بیایند.

---

# 29. Matching Semantics Are Not Data Types

نوع attribute به‌تنهایی matching semantics را مشخص نمی‌کند.

مثلاً عدد 51 نسبت به 49 ذاتاً بهتر یا بدتر نیست.

بنابراین این mapping ممنوع است:

```text
number
→ numeric distance
```

بدون policy صریح.

---

# 30. Specification Operators v1

Operators اولیه:

```text
EXACT
MIN_REQUIRED
MAX_ALLOWED
TARGET_WITH_TOLERANCE
IGNORE
```

معنا:

### EXACT

Candidate value باید با target value برابر باشد.

### MIN_REQUIRED

Candidate value باید حداقل مقدار RFQ را پوشش دهد.

### MAX_ALLOWED

Candidate value نباید از سقف RFQ عبور کند.

### TARGET_WITH_TOLERANCE

فاصله از target با tolerance versioned ارزیابی می‌شود.

### IGNORE

Attribute برای matching score استفاده نمی‌شود.

---

# 31. Specification Rule Configuration

Matching rule نباید داخل CommodityAttributeDefinition به‌عنوان matching metadata ذخیره شود.

Rule متعلق به Matching Policy است.

Conceptual model:

```text
SpecificationMatchingRule
```

حداقل metadata:

```text
policy_version
semantic_identity
operator
hard_constraint
relative_weight
tolerance
missing_data_policy
```

در v1:

```text
missing_data_policy = UNKNOWN
```

مگر یک requirement صریح خلاف آن داشته باشد.

---

# 32. Specification Dimension Weight Distribution

وزن کل Specification برای Direct Supply:

```text
45
```

Ruleهای applicable داخل RFQ دارای relative weight هستند.

Engine relative weightها را در همان RFQ normalize می‌کند تا مجموع contribution این dimension حداکثر 45 باشد.

Attributesی که RFQ اصلاً مقدارشان را مشخص نکرده است، applicable نیستند.

Attributeهای RFQ که MatchingRule ندارند:

```text
UNKNOWN
reason = matching_rule_not_configured
```

Engine نباید semantics حدس بزند.

---

# 33. Semantic Identity Foundation

Cross-schema compatibility به semantic identity نیاز دارد.

به‌جای اینکه key را semantic identity فرض کنیم، یک identity پایدار و مستقل لازم است.

مدل پیشنهادی:

```text
CommodityAttributeSemanticIdentity
```

حداقل:

```text
id / semantic_fingerprint
commodity
created_at
```

و:

```text
CommodityAttributeDefinition
→ semantic_identity
```

`semantic_fingerprint` می‌تواند همان UUID پایدار semantic identity باشد.

این fingerprint یک hash خودکار از تمام metadata نیست.

هدف آن stable semantic identity است.

---

# 34. Why Fingerprint Is Not a Raw Metadata Hash

اگر fingerprint مستقیماً hash همه metadata باشد، تغییر presentation metadata مانند موارد زیر compatibility را بی‌دلیل می‌شکند:

```text
label_fa
label_en
sort_order
display_group
```

از طرف دیگر یک hash ساده ممکن است expansionهای سازگار enum یا validation range را نیز به‌صورت غیرضروری incompatibility اعلام کند.

بنابراین fingerprint باید explicit semantic identity باشد.

---

# 35. Semantic Identity Lifecycle

وقتی schema جدید از schema قبلی clone می‌شود:

### Semantics unchanged

```text
reuse semantic identity
```

### Semantics changed

```text
create new semantic identity
```

بعد از Published شدن schema، semantic identity attribute immutable است.

---

# 36. Semantic Compatibility Guard

دو Attribute Definition که semantic identity یکسان دارند باید حداقل compatibility پایه را حفظ کنند.

v1 validation باید جلوی equivalence نادرست را بگیرد.

حداقل موارد ناسازگار:

```text
data type changed incompatibly
canonical unit meaning changed
enum domain meaning changed incompatibly
```

Presentation metadata می‌تواند تغییر کند بدون rotate شدن semantic identity.

Published policy باید conservative باشد.

اگر compatibility قابل اثبات نیست، fingerprint باید rotate شود.

---

# 37. Existing Data Backfill Policy

Migration نباید صرفاً از یکسان بودن key نتیجه بگیرد دو attribute تاریخی semantic identity مشترک دارند.

برای existing definitions:

> Default safe backfill = one semantic identity per existing Attribute Definition unless equivalence explicitly reviewed.

این policy false compatibility را ترجیحاً به missed compatibility تبدیل می‌کند.

برای deterministic seedهای فعلی می‌توان semantic identityهای پایدار و explicit تعریف کرد.

---

# 38. Cross-schema Matching Algorithm

برای attribute هدف:

```text
RFQ Attribute Definition
→ semantic identity
```

سپس در Candidate schema:

```text
find Attribute Definition with same semantic identity
```

اگر پیدا شد و compatibility guard پاس شد:

```text
compare values using Matching Policy rule
```

اگر پیدا نشد:

```text
UNKNOWN
```

این موارد ممنوع هستند:

```text
compare by key only
compare by localized label
reinterpret candidate using current active schema
```

---

# 39. Historical Schema Integrity

Matching همیشه از schema version ذخیره‌شده روی هر business record استفاده می‌کند.

```text
RFQ.schema_version
Candidate.schema_version
```

Engine نباید active schema فعلی Commodity را جایگزین هیچ‌کدام کند.

تغییر active schema بعد از ایجاد record نباید معنای MatchingRun تاریخی را تغییر دهد.

---

# 40. Matching Policy Versioning

Matching configuration باید versioned باشد.

مدل پیشنهادی:

```text
MatchingPolicy
MatchingPolicyVersion
```

Lifecycle:

```text
Draft
Published
Retired
```

Published policy immutable است.

هر MatchingRun دقیقاً به یک Published policy version اشاره می‌کند.

تغییر weight، operator، trust mapping یا threshold به معنی policy version جدید است.

Historical MatchingRun با policy جدید reinterpret نمی‌شود.

---

# 41. Policy Configuration Models

پیشنهاد relational:

```text
MatchingPolicy
MatchingPolicyVersion
MatchingDimensionWeight
SpecificationMatchingRule
VerificationMatchingRule
```

`MatchingDimensionWeight` حداقل شامل:

```text
policy_version
lane
dimension
weight
```

وزن‌های Published policy باید validation شوند.

برای هر lane مجموع dimension weightهای فعال باید 100 باشد.

---

# 42. No Generic Rules Builder UI

Epic 7 نباید low-code matching rules designer بسازد.

ممنوع در v1:

```text
drag/drop rule builder
arbitrary formulas
custom scripts
user-authored expressions
visual workflow designer
```

Policy initialization می‌تواند از deterministic seed یا controlled internal path استفاده کند.

---

# 43. Direct Supply Policy v1

Dimension weights:

```text
SPECIFICATION = 45
QUANTITY      = 10
AVAILABILITY  = 15
GEOGRAPHY     = 10
TRUST         = 15
HISTORY       = 5
```

این policy باید به‌صورت Published immutable configuration وجود داشته باشد، نه constants پراکنده در codebase.

---

# 44. Potential Supplier Lane

این lane supply واقعی را ادعا نمی‌کند.

Hard gates:

```text
active organization
Supplier capability
commodity association
not Suspended
not RFQ owner organization
```

نباید specification، quantity یا availability جعلی تولید شود.

v1 relevance score فقط از signalهایی استفاده می‌کند که واقعاً وجود دارند.

Default technical policy:

```text
Geography    40
Trust        60
```

History تا زمانی که provider واقعی وجود ندارد:

```text
NOT_APPLICABLE
```

Score این lane با Direct Supply Score قابل مقایسه نیست.

---

# 45. Broker Lane

Hard gates:

```text
active organization
Broker capability
commodity association
not Suspended
not RFQ owner organization
```

Broker score معنای Supply Fit ندارد.

نام مفهومی:

```text
Broker Relevance Score
```

Default v1 technical policy:

```text
Geography    40
Trust        60
```

Historical broker performance بعداً با policy version جدید فعال می‌شود.

Broker ranking فقط داخل Broker lane انجام می‌شود.

---

# 46. Qualified Supply Opportunity Lane Behavior

Opportunity candidate باید:

```text
direction = Supply
status = Qualified
commodity = RFQ commodity
```

باشد.

Candidate می‌تواند internal Organization counterparty یا ExternalCounterparty داشته باشد.

اگر اطلاعات quantity/specification/availability موجود نباشد، corresponding signals Unknown می‌شوند.

Opportunity Desk internal fields نباید به Buyer leak شوند.

---

# 47. Buyer Privacy for External Opportunities

Buyer هیچ‌کدام از اطلاعات زیر را از matching دریافت نمی‌کند:

```text
ExternalCounterparty identity
phone
email
Operator notes
Contact Attempts
internal qualification details
Opportunity identifier
Broker attribution of hidden Opportunity
```

در واقع Buyer-run provider اصلاً Qualified Opportunity source را query نمی‌کند.

بنابراین حتی candidate count نیز نباید وجود hidden Opportunities را لو بدهد.

---

# 48. Broker Attribution Is Not Supplier Trust

اگر External Supply Opportunity از Broker Referral آمده باشد:

```text
Broker attribution
```

باید برای Operator traceable باقی بماند، اما verification آن Broker نباید به‌صورت خودکار trust score Supplier خارجی محسوب شود.

Broker و external supplier دو actor مستقل هستند.

---

# 49. Persistence Strategy

Roadmap اجازه persisted یا reproducible بودن result را می‌دهد.

v1 این تصمیم را می‌گیرد:

> Matching results are persisted as immutable snapshots with reproducibility metadata.

دلایل:

- source data بعداً تغییر می‌کند؛
- verification تغییر می‌کند؛
- policy version تغییر می‌کند؛
- availability و quantity تغییر می‌کنند؛
- audit باید بتواند توضیح دهد چرا نتیجه قبلی آن score را داشته است.

---

# 50. MatchingRun Model

مدل مفهومی:

```text
MatchingRun
```

حداقل fields:

```text
id
rfq
rfq_version
audience
requesting_organization
requested_by
policy_version
engine_version
target_snapshot
input_fingerprint
result_fingerprint
generated_at
```

Run بعد از completion immutable است.

No normal update/delete API.

---

# 51. MatchingCandidate Model

مدل مفهومی:

```text
MatchingCandidate
```

حداقل:

```text
run
lane
candidate_kind
source FK
candidate_snapshot
eligible
exclusion_code
fit_score
evidence_coverage
ranking_score
rank
```

Candidate snapshot باید فقط data لازم برای matching/explanation و audience مناسب را ذخیره کند.

نباید raw model dump باشد.

---

# 52. Typed Candidate References

از GenericForeignKey استفاده نشود.

پیشنهاد:

```text
supplier_organization
supply_listing
supply_opportunity
broker_organization
```

به‌صورت nullable typed foreign keys.

DB constraint:

```text
exactly one candidate source FK must be non-null
```

برای هر source type باید duplicate candidate در یک run با unique constraint مناسب جلوگیری شود.

---

# 53. MatchingSignal Model

مدل مفهومی:

```text
MatchingSignal
```

حداقل:

```text
candidate
dimension
code
outcome
is_hard
weight
raw_score
contribution
expected_value
actual_value
reason_code
semantic_identity
```

Expected/actual values می‌توانند JSONB محدود و structured باشند.

Signal نباید localized explanation string را به‌عنوان source of truth ذخیره کند.

---

# 54. Explainability Contract

هر score باید به signalهای structured قابل تجزیه باشد.

مثال:

```text
code: spec.penetration_grade
outcome: PASS
expected: 60_70
actual: 60_70
weight: 20
contribution: 20
```

یا:

```text
code: availability
outcome: PARTIAL
expected: 2026-10-01..2026-10-15
actual: 2026-10-10..2026-10-30
raw_score: 0.40
```

UI reason_code را localized می‌کند.

---

# 55. Snapshot Immutability

بعد از ایجاد MatchingRun، تغییر sourceهای فعلی نباید snapshot تاریخی را rewrite کند.

مثلاً اگر Supply Listing quantity از 500 به 200 تغییر کرد:

```text
Old MatchingRun
→ remains unchanged

New MatchingRun
→ uses current source data
```

---

# 56. Input Fingerprint

برای reproducibility یک canonical input fingerprint ذخیره شود.

Conceptually:

```text
SHA-256(
  canonical target snapshot
  + ordered candidate snapshots
  + policy version
  + engine version
  + audience
)
```

Canonical serialization باید deterministic باشد:

```text
stable key ordering
stable datetime representation
stable Decimal representation
stable candidate ordering
```

Fingerprint برای authorization یا cryptographic signing استفاده نمی‌شود؛ هدف reproducibility/debugging است.

---

# 57. Result Fingerprint

نتیجه مرتب‌شده Candidates و Signals می‌تواند یک result fingerprint deterministic داشته باشد.

هدف:

```text
same inputs + same policy + same engine
→ same result fingerprint
```

این assertion باید در automated tests وجود داشته باشد.

---

# 58. Engine Version

MatchingRun باید یک engine contract version ذخیره کند.

مثلاً:

```text
matching-engine-v1
```

این version با deployment commit SHA یکی نیست.

تغییر semantics محاسبه که historical reproducibility را عوض می‌کند باید engine version جدید داشته باشد.

---

# 59. Deterministic Ranking

ترتیب v1 داخل هر lane:

```text
eligible DESC
ranking_score DESC
evidence_coverage DESC
fit_score DESC
stable_candidate_key ASC
```

Tie نباید به database row order وابسته باشد.

Rank فقط داخل همان lane معنا دارد.

Cross-lane rank وجود ندارد.

---

# 60. Excluded Candidates

Candidateهای discovered که Hard Failure می‌گیرند می‌توانند برای audit در run persist شوند.

اما API عادی Buyer نباید آنها را در پیشنهادهای معمول نمایش دهد.

Operator diagnostic access می‌تواند later اضافه شود.

Persist شدن excluded candidate نباید privacy boundary را دور بزند؛ candidate universe از ابتدا audience-scoped است.

---

# 61. Run Consistency and PostgreSQL Snapshot

MatchingRun باید از یک consistent database view ساخته شود.

Preferred v1 execution:

```text
PostgreSQL transaction
→ REPEATABLE READ
→ load target snapshot
→ discover authorized candidates
→ materialize candidate snapshots
→ evaluate
→ persist run/candidates/signals atomically
→ COMMIT
```

هدف این است که Candidate A از قبل یک update و Candidate B از بعد همان update در یک run خوانده نشوند.

هیچ row lock گسترده برای analytical matching لازم نیست مگر برای invariant مشخص.

---

# 62. Matching Failure Atomicity

اگر scoring، persistence یا explanation generation fail شود:

```text
no partial MatchingRun
no partial candidate set
no partial signal history
```

Run باید یا کامل persist شود یا اصلاً وجود نداشته باشد.

---

# 63. Rerun Semantics

MatchingRun historical است.

Rerun نتیجه قبلی را overwrite نمی‌کند.

```text
Run 1
Run 2
Run 3
```

هر کدام timestamp، policy version، target version و snapshot مستقل دارند.

UI می‌تواند latest run را default نشان دهد، ولی historical runs حذف نمی‌شوند.

---

# 64. Staleness

API باید حداقل بتواند target staleness را تشخیص دهد.

اگر:

```text
run.rfq_version != current RFQ.version
```

result باید به‌عنوان stale target شناخته شود.

MatchingRun خودکار mutate یا auto-refresh نمی‌شود.

Candidate-source freshness در v1 از snapshot timestamp قابل مشاهده است؛ system نباید ادعا کند historical result live است.

---

# 65. No Background Infrastructure

Epic 7 برای v1 نیازی به موارد زیر ندارد:

```text
Celery
Kafka
RabbitMQ
Redis
Temporal
Elasticsearch
Vector DB
```

Matching synchronous/application-service based است مگر performance evidence واقعی خلاف آن را ثابت کند.

---

# 66. Query Strategy

Candidate discovery ابتدا با relational filters candidate universe را کوچک می‌کند.

```text
PostgreSQL
→ lifecycle / capability / commodity / visibility filtering

Python domain engine
→ detailed matching and scoring
```

Specification JSONB نباید از روز اول به یک SQL scoring engine پیچیده تبدیل شود.

---

# 67. JSONB Indexing Policy

Index فقط بر اساس query pattern واقعی و measurement اضافه شود.

اگر candidate discovery عمدتاً با relational fields انجام می‌شود، GIN index عمومی روی specifications صرفاً برای احساس performance readiness اضافه نشود.

هر index جدید باید query evidence داشته باشد.

---

# 68. Performance Boundary

Pilot scale اولویت دارد.

Requirementها:

- obvious N+1 ممنوع؛
- candidate provider query counts قابل مشاهده باشند؛
- scoring deterministic باشد؛
- memory usage برای demo/pilot معقول باشد؛
- premature distributed architecture ممنوع.

Epic Review Gate باید representative query count و runtime را ثبت کند، اما benchmark عددی مصنوعی بدون dataset واقعی release gate نیست.

---

# 69. Matching API

Route naming دقیق مطابق repository conventions نهایی می‌شود.

Conceptual API:

```text
POST /api/matching/rfqs/{rfq_id}/runs/
GET  /api/matching/rfqs/{rfq_id}/runs/
GET  /api/matching/runs/{run_id}/
GET  /api/matching/runs/{run_id}/candidates/
```

Candidate list باید lane filter داشته باشد:

```text
DIRECT_SUPPLY
POTENTIAL_SUPPLIER
BROKER_PATH
```

---

# 70. Matching Trigger Authorization

ایجاد MatchingRun باید از authorization واقعی RFQ management استفاده کند.

Capability به‌تنهایی permission نیست.

حداقل:

```text
Authorized Buyer-side RFQ manager
Operator
Product Admin
```

می‌توانند run ایجاد کنند.

Supplier/Broker صرفاً به دلیل دیدن RFQ نمی‌توانند matching intelligence مالک RFQ را ببینند یا run ایجاد کنند.

Django staff/superuser flags به‌تنهایی Product authority نیستند.

---

# 71. Buyer Projection

Buyer candidate projection باید فقط safe business information را expose کند.

Buyer نباید internal Opportunity Desk data یا hidden source attribution دریافت کند.

Candidate snapshot/API باید explicit projection داشته باشد، نه generic model serializer.

---

# 72. Operator Projection

Operator می‌تواند source context بیشتری ببیند، از جمله:

```text
Opportunity source reference
External vs internal counterparty type
Broker attribution where operationally required
```

اما Matching API باز هم نباید Contact Attempt notes، phone/email یا private operational data غیرمرتبط را کپی کند.

Principle:

> Matching stores matching evidence, not a duplicate CRM snapshot.

---

# 73. Matching UI

Matching UI باید داخل context RFQ قابل دسترس باشد.

پیشنهاد:

```text
RFQ Workspace
→ Matches
```

سه section/lane:

```text
تأمین مستقیم
تأمین‌کنندگان بالقوه
مسیرهای بروکری
```

هر lane ranking مستقل دارد.

---

# 74. Candidate UI Card

Direct Supply حداقل می‌تواند نشان دهد:

```text
Fit Score
Evidence Coverage
Source Type
Verification
Top Positive Signals
Unknown / Missing Evidence
Important Constraint Warnings
```

Potential Supplier باید واضح بگوید supply availability اثبات نشده است.

Broker card باید از واژه Supply Match استفاده نکند.

---

# 75. Explainability UI

هر Candidate باید action مفهومی زیر داشته باشد:

```text
Why this match?
```

پنل explanation باید structured signals را نمایش دهد.

Score بدون explanation نباید تنها output اصلی UI باشد.

---

# 76. Candidate Actions

Matching UI فقط actionهای domain موجود را invoke می‌کند.

مثال:

### Supplier Organization

```text
Invite to RFQ
```

### Supply Listing

```text
View Listing
Invite Supplier
```

### Qualified Opportunity

Operator only:

```text
Open Opportunity
```

### Broker

```text
Invite Broker
```

Matching service خودش action را اجرا نمی‌کند.

---

# 77. Localization

UI demo فعلی Persian/RTL است.

Engine فقط machine-readable reason codes ذخیره می‌کند.

مثلاً:

```text
commodity_match
spec_exact_match
partial_quantity
availability_overlap
verified_organization
missing_candidate_spec
```

Persian labels در frontend localization layer قرار می‌گیرند.

Business logic نباید به Persian/English label وابسته باشد.

---

# 78. OpenAPI Contract

تمام Matching endpointها باید از chain فعلی استفاده کنند:

```text
Django API
→ OpenAPI
→ Generated TypeScript
→ Typed Frontend Client
```

DTO دستی موازی ممنوع است.

Contract باید دقیقاً شامل این مفاهیم باشد:

```text
lane
candidate kind
eligibility
fit score
evidence coverage
ranking score
structured signals
run metadata
staleness
```

---

# 79. Error Semantics

Business failures باید controlled باشند.

نمونه‌ها:

```text
RFQ not matchable
unauthorized
RFQ not found / hidden
no published matching policy
policy configuration invalid
unsupported target state
```

این موارد نباید 500 شوند.

Configuration corruption می‌تواند server error محسوب شود، اما باید observable و logged باشد.

---

# 80. No Score as a Business Guarantee

UI و API نباید score را به شکل probability of success معرفی کنند.

مثلاً 92% یعنی:

> Compatibility score under policy version X and currently available evidence.

نه:

> 92% probability of successful deal.

این distinction باید در naming و UI حفظ شود.

---

# 81. Epic 7 vs Epic 8 Boundary

Epic 7 نباید موارد زیر را وارد score کند:

```text
headline Offer price
landed cost
payment risk
negotiated discount
revision quality
award recommendation
```

این‌ها concern Epic 8 هستند.

Matching candidate selection با Offer comparison یکی نیست.

---

# 82. No Automatic Procurement Decision

Epic 7 نباید:

```text
auto-select supplier
auto-invite everyone
auto-award
auto-submit offer
```

انجام دهد.

Human remains decision maker.

---

# 83. No AI / ML in v1

نسخه اول rule-based و deterministic است.

ممنوع:

```text
LLM ranking
embedding similarity
vector search
ML recommendation
opaque learned scoring
```

اگر بعداً داده کافی ایجاد شد، ML می‌تواند یک signal provider جدید باشد، نه جایگزین explainable domain engine.

---

# 84. Database Integrity

تا جای ممکن structural integrity در PostgreSQL enforce شود.

حداقل:

- exactly one candidate source FK؛
- unique candidate source per run؛
- valid lane/candidate kind/outcome enums؛
- Published policy references؛
- positive valid weights؛
- valid score ranges؛
- referential integrity به RFQ/Organization/Supply/Opportunity؛
- immutable historical references با deletion policy مناسب.

Scoring formula نباید به CHECK constraint پیچیده تبدیل شود.

---

# 85. Delete / Retention Semantics

MatchingRun یک historical analytical record است.

RFQ و sourceهای مرتبط نباید از مسیر عادی طوری حذف شوند که run غیرقابل تفسیر شود.

Preferred behavior برای business records:

```text
PROTECT
```

در جاهایی که existing domain deletion policy اجازه حذف می‌دهد، snapshot باید meaning run را حفظ کند.

هیچ cascading delete ناخواسته‌ای نباید Matching history را نابود کند.

---

# 86. Sensitive Data Policy

Snapshotها فقط data لازم برای matching را نگه می‌دارند.

نباید موارد غیرضروری را duplicate کنند:

```text
phone
email
internal notes
contact attempt bodies
verification document metadata
raw object keys
session/security data
```

---

# 87. Logging

Logها نباید complete candidate snapshot یا private ExternalCounterparty data را چاپ کنند.

حداقل observability:

```text
run id
rfq id
audience
candidate counts by lane
eligible/excluded counts
policy version
engine version
runtime
```

نه PII/raw specs dump به‌صورت پیش‌فرض.

---

# 88. Deterministic Seed Policy

Epic 7 باید default Published Matching Policy v1 را به‌شکل deterministic/idempotent ایجاد کند.

Seed نباید Published historical policy را overwrite کند.

اگر policy v1 وجود دارد و semantics متفاوت است، seed باید conflict را report کند، نه silently mutate کند.

---

# 89. Recommended Task Execution Order

ترتیب اجرایی پیشنهادی بر اساس dependency واقعی:

```text
1. T0701 — Matching Candidate Model / Persistence Foundation
2. T0706 — Candidate Sources
3. T0702 — Core Matching Rules
4. T0703 — Dynamic Specification Matching
5. T0704 — Trust / Verification Signals
6. T0705 — Historical Signals
7. T0707 — Explainable Scoring
8. T0708 — Matching UI
9. Epic 7 Adversarial Review Gate
```

این ترتیب عمداً با ترتیب عددی کامل یکسان نیست.

---

# 90. T0701 Allocation

T0701 باید foundationهای لازم برای reproducibility را ایجاد کند:

```text
MatchingRun
MatchingCandidate
MatchingSignal
MatchingPolicy
MatchingPolicyVersion
```

همراه با:

- audience؛
- immutable snapshots؛
- typed candidate source references؛
- DB constraints؛
- engine version؛
- input/result fingerprint foundation.

نباید هنوز Candidate Providers یا scoring کامل را پیاده کند.

---

# 91. T0706 Allocation

T0706 Candidate Providers را می‌سازد:

```text
SupplyListingCandidateProvider
SupplyOpportunityCandidateProvider
SupplierOrganizationCandidateProvider
BrokerCandidateProvider
```

و باید authorization-before-scoring را اثبات کند.

Buyer provider set و Operator provider set باید متفاوت باشند.

---

# 92. T0702 Allocation

T0702 Core rules:

```text
commodity
capability
source lifecycle
self-match
quantity
availability
geography
```

را پیاده می‌کند.

Hard/Soft/Unknown semantics باید behavioral tests داشته باشد.

---

# 93. T0703 Allocation

T0703 مسئول این موارد است:

```text
semantic identity foundation
cross-schema compatibility
SpecificationMatchingRule
EXACT / MIN_REQUIRED / MAX_ALLOWED / TARGET_WITH_TOLERANCE
```

و generic multi-commodity proof.

این task ممکن است مدل CommodityAttributeDefinition را با semantic identity FK توسعه دهد، ولی نباید matching weight را داخل commodity definitions قرار دهد.

---

# 94. T0704 Allocation

T0704 verification mapping و Suspended exclusion را اضافه می‌کند.

باید Internal Organization و ExternalCounterparty را درست تفکیک کند.

---

# 95. T0705 Allocation

T0705 provider interface تاریخی و هر signal واقعی موجود را اضافه می‌کند.

اگر data source هنوز وجود ندارد:

```text
NOT_APPLICABLE
```

باید honest result باشد.

نباید fake historical fixtures را production logic جا بزند.

---

# 96. T0707 Allocation

T0707:

- dimension weights؛
- Fit Score؛
- Evidence Coverage؛
- Ranking Score؛
- lane-local ranking؛
- structured explanations؛
- deterministic fingerprints؛
- default Published policy v1؛
- final scoring integration

را کامل می‌کند.

---

# 97. T0708 Allocation

T0708 UI نهایی را روی backend contract پایدار می‌سازد.

UI باید:

- سه lane را جدا نشان دهد؛
- Buyer/Operator projection را رعایت کند؛
- score + coverage را نمایش دهد؛
- structured explanations را localized render کند؛
- stale run را مشخص کند؛
- existing invite/view actions را reuse کند؛
- هیچ Offer/Recommendation Epic 8 را پیاده نکند.

---

# 98. Automated Test Philosophy

تمام Acceptance Criteria مهم باید تا حد ممکن behavioral test داشته باشند.

هر automated test Definition of Done باید از canonical CI قابل اجرا باشد مگر صریحاً Review Gate-only تعریف شود.

Backend authoritative environment:

```text
PostgreSQL
```

SQLite fallback ممنوع است.

---

# 99. Required Backend Test Categories

حداقل:

## Persistence

- exactly-one source FK؛
- duplicate source per run rejected؛
- immutable completed run؛
- valid enum/score ranges؛
- policy immutability.

## Candidate Discovery

- each source provider؛
- wrong lifecycle exclusion؛
- capability guards؛
- self-match exclusion؛
- Buyer vs Operator candidate universe.

## Privacy

- Buyer cannot infer Qualified Opportunities؛
- no hidden opportunity counts؛
- Supplier/Broker cannot access matching intelligence؛
- Django flags alone grant no access.

## Core Rules

- commodity mismatch hard fail؛
- partial quantity score؛
- full quantity required hard fail؛
- availability full/partial/no overlap؛
- explicit geography fail؛
- unknown geography.

## Verification

- all statuses؛
- Suspended hard exclusion؛
- external trust Unknown.

## Dynamic Specs

- all operators؛
- same-schema matching؛
- same semantic identity cross-schema؛
- same key/different semantic identity must not compare؛
- current active schema must not replace record schema؛
- Bitumen/Base Oil through same engine.

## Scoring

- exact formula؛
- Unknown coverage behavior؛
- NOT_APPLICABLE denominator behavior؛
- deterministic rounding؛
- tie ordering؛
- cross-lane scores never globally ranked.

## Historical Integrity

- source mutation after run does not rewrite result؛
- policy v2 does not rewrite run from v1؛
- active schema change does not rewrite historical result.

---

# 100. Concurrency / Snapshot Tests

Real PostgreSQL tests باید prove کنند:

- یک MatchingRun partial persist نمی‌شود؛
- consistent snapshot semantics رعایت می‌شود؛
- source update هم‌زمان run را به mixed-state input تبدیل نمی‌کند؛
- identical deterministic inputs result fingerprint یکسان تولید می‌کنند.

اگر REPEATABLE READ implementation استفاده شود، تست باید واقعاً separate connections داشته باشد.

---

# 101. Frontend Test Requirements

حداقل component/integration coverage:

- three lanes render separately؛
- Direct Supply score + coverage؛
- Potential Supplier warning؛
- Broker Relevance label؛
- structured explanation rendering؛
- Buyer cannot render hidden Opportunity candidate fixture from real contract؛
- Operator can render qualified opportunity candidate؛
- stale run state؛
- loading/empty/error/unauthorized states؛
- Persian RTL labels؛
- generated API types only.

---

# 102. Epic-level Integration Flow

حداقل backend integration flow:

```text
Published RFQ
→ discover active Supply Listing
→ discover Supplier Organization
→ discover Broker
→ Operator additionally discovers Qualified Supply Opportunity
→ evaluate hard rules
→ evaluate specifications
→ trust signal
→ score
→ persist immutable run
→ retrieve structured explanation
```

Buyer variant:

```text
same RFQ
→ no Qualified Opportunity leakage
→ safe Supplier / Supply / Broker suggestions only
```

---

# 103. Hero Example

Target:

```text
RFQ
Commodity: Bitumen
Grade: 60/70
Quantity: 500 MT
Delivery: Oct 1–15
```

Candidate:

```text
Supply Listing
Grade: 60/70
Quantity: 300 MT
Availability: Oct 1–30
Supplier: Basic Verified
Geography: Unknown
History provider: Not Applicable
```

Signals:

```text
Specification     PASS      1.00 × 45 = 45.00
Quantity          PARTIAL   0.60 × 10 =  6.00
Availability      PASS      1.00 × 15 = 15.00
Geography         UNKNOWN                 --
Trust             PARTIAL   0.70 × 15 = 10.50
History           N/A                     --
```

Then:

```text
Applicable weight A = 95
Known weight K      = 85
Contribution C      = 76.5

Fit Score           = 90.00%
Evidence Coverage   = 89.47%
Ranking Score       = 80.53%
```

این مثال باید تقریباً به‌صورت executable scoring test وجود داشته باشد.

---

# 104. Matching UI Does Not Claim Probability

UI باید به‌جای عبارت‌هایی مانند:

```text
92% chance of success
```

از wordingی مانند این استفاده کند:

```text
Match Score
Compatibility
Evidence Coverage
```

score یک نتیجه policy-based است، نه forecast آماری.

---

# 105. Epic 7 Explicit Non-goals

این موارد در scope نیستند:

```text
AI matching
Machine Learning ranking
Embeddings
Vector Database
Elasticsearch
Generic Rules Builder
Automatic Supplier Selection
Automatic RFQ Invitation
Automatic Broker Assignment
Offer creation
Offer comparison
Landed cost
Price recommendation
Negotiation
Award
Deal creation
Execution workflow
Payment / settlement
Generic analytics platform
Generic notification platform
```

---

# 106. Architecture Failure Conditions

Epic 7 از نظر معماری fail محسوب می‌شود اگر یکی از اینها لازم شود:

```python
if commodity.code == "bitumen":
```

داخل generic matching engine.

یا:

```text
same attribute key
→ assumed same semantics across versions
```

یا:

```text
Unknown
→ silently treated as Match
```

یا:

```text
Suspended organization
→ still eligible because other scores are high
```

یا:

```text
Broker score
→ globally ranked against Supply Listing score
```

یا:

```text
Buyer
→ can infer hidden Qualified External Opportunities
```

یا:

```text
current active schema
→ used to reinterpret historical candidate
```

یا:

```text
Matching run
→ mutates RFQ / Opportunity / Invitation / Offer
```

یا:

```text
score
→ cannot be decomposed into stored structured signals
```

---

# 107. Definition of Done

Epic 7 فقط وقتی موفق است که بتوان این flow را با داده واقعی repository اثبات کرد:

```text
Published RFQ
→ Candidate Discovery from multiple source kinds
→ Authorization applied before scoring
→ Hard eligibility
→ Generic specification matching
→ Trust signals
→ Honest missing-history behavior
→ Lane-specific deterministic scoring
→ Evidence Coverage
→ Structured Explanation
→ Immutable persisted MatchingRun
→ Persian RTL UI
```

و هم‌زمان:

```text
Buyer cannot see hidden Opportunity candidates
Broker is not treated as Supplier
Partial quantity is not incorrectly rejected
Suspended organization cannot rank
Different schema versions are compared only through semantic identity
Historical runs remain stable after source/policy/schema changes
```

---

# 108. Required Epic 7 Review Gate Checks

Codex Epic Review Gate باید فراتر از suite موجود این موارد را attack کند.

## Target

- فقط RFQ target v1؛
- Draft cannot match؛
- unauthorized foreign RFQ cannot run matching.

## Candidate Universe

- all four roadmap sources discoverable where authorized؛
- Buyer and Operator universes differ correctly؛
- no hidden-count leakage.

## Lanes

- Direct Supply / Potential Supplier / Broker Path separate؛
- no cross-lane rank.

## Eligibility

- commodity mismatch؛
- wrong capability؛
- Suspended؛
- inactive source؛
- self-match؛
- no availability overlap؛
- mandatory geography violation.

## Quantity

- exact quantity؛
- over-supply capped at full score؛
- partial quantity scored؛
- explicit full-quantity requirement rejects shortage.

## Geography

- hard only when explicit؛
- no invented distance/logistics score.

## Verification

- exact mapping of all six states؛
- external trust Unknown؛
- broker trust does not transfer to external supplier.

## Dynamic Specifications

- no Bitumen conditional؛
- all operators؛
- Base Oil same engine؛
- missing value Unknown؛
- no key-only cross-schema match.

## Semantic Identity

- clone preserves identity when semantics unchanged؛
- semantic change rotates identity؛
- Published identity immutable؛
- unsafe migration inference absent.

## Scoring

- formula exact؛
- Decimal deterministic؛
- Unknown coverage؛
- N/A denominator؛
- deterministic ranking/ties.

## Persistence

- run/candidates/signals immutable؛
- no partial persistence؛
- source mutation does not rewrite run؛
- policy changes do not rewrite history.

## Reproducibility

- identical snapshots + policy + engine produce same fingerprints/results.

## Security

- Buyer cannot inspect Opportunity Desk internals؛
- Supplier/Broker cannot inspect buyer matching intelligence؛
- Django superuser without Product Role does not bypass؛
- no sensitive snapshot/log leakage.

## API Contract

- OpenAPI matches real wire behavior؛
- generated TypeScript deterministic؛
- no handwritten DTO bypass.

## Performance

- candidate discovery has no obvious N+1؛
- representative run query/runtime evidence recorded؛
- no premature infra/indexing.

## Frontend

- Persian RTL؛
- lane labels correct؛
- score + coverage؛
- explanations؛
- stale state؛
- loading/empty/error/auth boundaries.

## Scope

- no Offer comparison؛
- no recommendation engine Epic 8؛
- no AI/ML؛
- no new infrastructure category.

---

# 109. CI Requirements

تمام automated tests Task DoD باید از canonical CI path قابل دسترسی باشند.

Backend:

```text
python manage.py test
→ PostgreSQL CI
```

Frontend:

```text
canonical repository frontend tests
→ GitHub frontend job
```

Contract:

```text
OpenAPI validation
→ TypeScript generation
→ drift check
```

اگر browser E2E در Task DoD اضافه شود، باید یا وارد canonical CI شود یا صریحاً Epic Review Gate-only اعلام شود.

---

# 110. Long-term Contract

بعد از Epic 7، سیستم این foundation را خواهد داشت:

```text
Versioned Commodity Semantics
        ↓
RFQ Demand Snapshot
        ↓
Authorized Candidate Sources
        ↓
Versioned Matching Policy
        ↓
Hard Eligibility
        ↓
Explainable Compatibility Signals
        ↓
Lane-specific Ranking
        ↓
Immutable Matching Snapshot
```

Epicهای بعدی می‌توانند بدون شکستن این foundation موارد زیر را اضافه کنند:

```text
real historical deal signals
execution performance signals
new matching policy versions
additional candidate providers
Demand Opportunity targets
carefully justified ML signals
```

اما historical MatchingRunها همیشه باید با semantics زمان خودشان قابل تفسیر باقی بمانند.

---

# 111. Final Architectural Statement

Epic 7 نباید صرفاً یک query با چند weight و یک درصد خروجی باشد.

خروجی واقعی این Epic باید یک قرارداد پایدار باشد:

> Matching یک pipeline versioned، deterministic، explainable و audience-aware است که evidenceهای ناهمگون را بدون جعل certainty مقایسه می‌کند، compatibility را از procurement decision جدا نگه می‌دارد، و هر نتیجه را با policy و snapshot زمان خودش قابل audit می‌سازد.

اصل نهایی:

```text
Discovery ≠ Eligibility ≠ Scoring ≠ Decision

Unknown ≠ Mismatch

Broker ≠ Supplier

Semantic Identity ≠ Attribute Key

Historical Snapshot ≠ Current State

Matching Score ≠ Probability of Success
```
