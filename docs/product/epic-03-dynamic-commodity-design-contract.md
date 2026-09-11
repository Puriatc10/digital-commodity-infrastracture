# Epic 3 — Dynamic Commodity Model

## Design Contract, Architectural Invariants & Functional Requirements

> Status: Product-owner-approved authoritative detailed implementation contract for Epic 3. Read this entire contract alongside the [Product Specification](product-spec.md) for product scope and the [Delivery Roadmap](../delivery/roadmap.md) for T0301–T0308 delivery and review gates. This document is persisted in full for fresh Jules sessions and the Codex Epic 3 Review Gate; approval of the design does not authorize implementation during the documentation synchronization task.
>
> Owner synchronization clarification: the task mapping in §73 is the approved mapping. An active schema must belong to the same Commodity and be Published; Draft/Retired versions are not usable for new instances. Optional fields may be absent and are not automatically nullable; explicit null requires schema support. These requirements govern the softer “suggested/preferably” wording below.


این سند باید به‌عنوان **Design Contract اپیک ۳** در نظر گرفته شود و مبنای طراحی Taskها، پیاده‌سازی Jules و در نهایت Codex Epic Review Gate باشد.

هدف این سند این است که قبل از شروع implementation، دقیقاً مشخص باشد:

* چه مسئله‌ای را حل می‌کنیم؛
* چه مدل داده‌ای می‌خواهیم؛
* چه invariantهایی غیرقابل شکستن هستند؛
* چه functionalityهایی باید تا پایان Epic وجود داشته باشند؛
* چه چیزهایی عمداً نباید در این Epic ساخته شوند؛
* و در Review Gate دقیقاً چه چیزی باید اثبات شود.

---

# 1. Epic Objective

هدف Epic 3 ساخت یک:

> **Versioned Dynamic Commodity Definition & Specification Foundation**

است.

این foundation باید اجازه دهد Commodityهای مختلف specificationهای کاملاً متفاوت داشته باشند، بدون اینکه برای هر Commodity جدید مجبور شویم:

* Django model جدید ایجاد کنیم؛
* column جدید به domain tables اضافه کنیم؛
* migration جدید برای specification fields بسازیم؛
* backend validator مخصوص آن Commodity بنویسیم؛
* frontend form مخصوص آن Commodity بسازیم.

Bitumen اولین و اصلی‌ترین Commodity محصول است.

Base Oil در این Epic فقط برای اثبات extensibility معماری استفاده می‌شود.

---

# 2. Core Architectural Principle

مدل باید **Hybrid Relational + Dynamic JSONB** باشد.

تعریف Specificationها:

```text
Relational + Versioned
```

مقادیر Specification مربوط به domain instances آینده:

```text
JSONB
```

یعنی:

```text
CommodityDefinition
        │
        └── CommoditySchemaVersion
                    │
                    └── CommodityAttributeDefinition
```

تعریف می‌کند که یک Commodity چه specificationهایی دارد.

در Epicهای بعدی entityهایی مانند:

```text
RFQ
Supply Listing
Opportunity
Offer
```

به‌جای داشتن ستون‌های commodity-specific، چیزی شبیه این خواهند داشت:

```text
commodity_id
schema_version_id
specifications JSONB
```

---

# 3. Critical Invariant — No Commodity-specific Core Columns

این یکی از مهم‌ترین invariantهای کل پروژه است.

نباید core models به شکلی مانند زیر تبدیل شوند:

```text
RFQ
├── penetration_grade
├── softening_point
├── ductility
├── viscosity_index
├── pour_point
├── sulfur_content
└── ...
```

هیچ property اختصاصی Bitumen، Base Oil یا Commodity دیگری نباید وارد مدل عمومی RFQ / Offer / Supply / Opportunity شود.

به‌صورت مفهومی باید همیشه:

```text
Core Commercial Fields
+
Dynamic Commodity Specifications
```

داشته باشیم.

---

# 4. Critical Invariant — Definition ≠ Instance Value

دو مفهوم کاملاً جدا هستند:

## Definition

می‌گوید:

> `softening_point` چیست، چه نوع داده‌ای دارد، required است یا نه، unit چیست و چگونه validate می‌شود.

این relational است.

## Instance Value

می‌گوید:

> Softening Point این RFQ خاص برابر 49 است.

این بعداً داخل `specifications JSONB` قرار می‌گیرد.

بنابراین:

```text
CommodityAttributeDefinition
```

نباید محل ذخیره actual RFQ/Offer values باشد.

---

# 5. CommodityDefinition

مدل `CommodityDefinition` نماینده نوع Commodity است.

نمونه:

```text
code: bitumen
name_fa: قیر
name_en: Bitumen
status: active
```

حداقل semantics موردنیاز:

* stable identifier
* unique canonical code
* Persian label/name
* English label/name
* active/inactive state
* timestamps where consistent with project conventions
* reference to active schema version

### Rules

`code` باید machine-readable و stable باشد.

مثلاً:

```text
bitumen
base_oil
```

نه label فارسی.

UI نباید از code به‌عنوان label استفاده کند.

`code` نباید به معنی database table یا Python class مخصوص Commodity باشد.

---

# 6. Commodity Schema Version

هر Commodity باید specification definition نسخه‌دار داشته باشد.

مدل مفهومی:

```text
CommodityDefinition
    ├── Schema Version 1
    ├── Schema Version 2
    └── ...
```

مثلاً:

```text
Bitumen
├── v1 Published
└── v2 Draft
```

هر `CommoditySchemaVersion` باید حداقل شامل:

```text
commodity
version
status
timestamps
```

باشد.

ترکیب:

```text
commodity + version
```

باید unique باشد.

مثلاً دو `Bitumen v1` نباید وجود داشته باشند.

---

# 7. Schema Lifecycle

در v1 فقط سه state نیاز داریم:

```text
Draft
Published
Retired
```

### Draft

قابل تغییر است.

برای طراحی نسخه بعدی استفاده می‌شود.

### Published

نسخه authoritative و قابل استفاده برای domain instances است.

باید immutable باشد.

### Retired

نسخه historical است که دیگر برای ایجاد instance جدید استفاده نمی‌شود، ولی باید برای render/validation historical records قابل دسترسی باقی بماند.

---

# 8. Critical Invariant — Published Schemas Are Immutable

وقتی Schema Published شد، semantics آن دیگر نباید تغییر کند.

بعد از publish نباید بتوان:

* attribute اضافه کرد؛
* attribute حذف کرد؛
* key را تغییر داد؛
* type را تغییر داد؛
* required را تغییر داد؛
* enum semantics را تغییر داد؛
* validation rules را تغییر داد؛
* unit semantics را silently تغییر داد.

اگر definition نیاز به تغییر دارد:

```text
v1 Published
        ↓
create
        ↓
v2 Draft
        ↓
v2 Published
```

نه:

```text
edit v1 in place
```

Historical interpretation باید deterministic باقی بماند.

---

# 9. Active Schema Version

هر Commodity می‌تواند یک active/current schema داشته باشد که domain objects جدید در آینده از آن استفاده کنند.

مفهوم:

```text
CommodityDefinition.active_schema_version
```

### Critical Integrity Rule

Active schema باید متعلق به همان Commodity باشد.

این وضعیت باید impossible باشد:

```text
Commodity = Bitumen

active_schema_version =
Base Oil v1
```

همچنین active schema باید یک version قابل استفاده باشد؛ ترجیحاً فقط `Published`.

وجود Commodity بدون active schema در مرحله Draft/Setup می‌تواند قابل قبول باشد.

اما Commodity فعال و قابل استفاده در business workflow باید active published schema مشخص داشته باشد.

---

# 10. CommodityAttributeDefinition

هر Schema Version مجموعه‌ای از Attribute Definitionها دارد.

مثلاً:

```text
Bitumen v1

penetration_grade
penetration
softening_point
ductility
flash_point
...
```

هر Attribute باید metadata کافی برای:

* backend validation;
* frontend rendering;
* frontend display;
* future matching/querying;

داشته باشد، بدون اینکه وارد logic اپیک‌های بعدی شویم.

حداقل conceptها:

```text
key
label_fa
label_en
data_type
required
unit metadata
enum options
validation rules
display_group
sort_order
```

---

# 11. Attribute Key

`key` باید canonical و machine-readable باشد.

مثلاً:

```text
penetration_grade
softening_point
viscosity_index
```

Rules:

* unique داخل یک Schema Version؛
* independent from translated labels؛
* stable after publish؛
* snake_case یا convention ثابت project؛
* frontend/backend نباید روی Persian label business logic داشته باشند.

این غلط است:

```text
if label == "نقطه نرمی":
```

این درست است:

```text
softening_point
```

---

# 12. Attribute Types Supported in Epic 3

عمداً type system را کوچک نگه می‌داریم.

حداقل supported types:

```text
string
number
integer
boolean
enum
```

این typeها باید end-to-end کار کنند:

```text
Definition
→ Generated Validation Schema
→ Backend Validation
→ OpenAPI/API Representation
→ Frontend Dynamic Renderer
```

### Explicit Non-goals

در Epic 3 نیاز نداریم:

```text
nested object
arbitrary arrays
formula fields
calculated fields
conditional form logic
complex multi-select
recursive schemas
custom scripting
```

اگر later نیاز واقعی ایجاد شد، versioned extension اضافه می‌کنیم.

---

# 13. Flat Specification Structure

Specification payloadهای v1 باید flat باشند.

مثال صحیح:

```json
{
  "penetration_grade": "60_70",
  "penetration": 65,
  "softening_point": 49,
  "ductility": 102
}
```

فعلاً مدل پیچیده زیر نمی‌خواهیم:

```json
{
  "physical": {
    "penetration": {
      "value": 65,
      "unit": "dmm"
    }
  }
}
```

Flat structure باعث ساده‌تر شدن:

* validation
* API
* frontend forms
* comparison
* matching
* querying
* future indexing

می‌شود.

---

# 14. Unit Semantics

Unit بخشی از Attribute Definition است.

مثلاً:

```text
key:
softening_point

data_type:
number

unit:
°C
```

و actual specification:

```json
{
  "softening_point": 49
}
```

است.

نه:

```json
{
  "softening_point": {
    "value": 49,
    "unit": "C"
  }
}
```

در این Epic Unit Conversion Engine ساخته نمی‌شود.

اگر attribute ممکن است later چند unit داشته باشد، model می‌تواند metadata مناسب مانند:

```text
unit_family
allowed_units
canonical_unit
```

را accommodate کند، ولی implementation نباید تبدیل واحد پیچیده ایجاد کند مگر واقعاً برای v1 لازم باشد.

### Important distinction

Quantity اصلی معامله مثل:

```text
500 MT
```

جزو commercial core است و در آینده relational خواهد بود.

Commodity specification unit با trade quantity یکی نیست.

---

# 15. Enum Semantics

Enumها باید canonical machine values داشته باشند.

مثلاً:

```text
key:
penetration_grade

value:
60_70

label_fa:
60/70

label_en:
60/70
```

Actual stored value:

```json
{
  "penetration_grade": "60_70"
}
```

نه localized UI label.

این برای:

* future English UI;
* matching;
* analytics;
* APIs;
* schema versioning;

ضروری است.

---

# 16. Localization

Definition باید localization-ready باشد.

Demo فعلی Persian/RTL است، ولی architecture آینده English/LTR را پشتیبانی می‌کند.

در نتیجه Attribute Definition و Commodity Definition باید حداقل labelهای موردنیاز برای:

```text
fa
en
```

را داشته باشند.

Reusable frontend components نباید Persian strings را مستقیماً hard-code کنند.

Current demo UI:

```text
Persian + RTL
```

ولی underlying data model locale-aware باقی می‌ماند.

---

# 17. Validation Source of Truth

نباید دو schema مستقل داشته باشیم که ممکن است drift کنند.

یعنی نباید:

```text
CommodityAttributeDefinition
```

یک source باشد و همزمان:

```text
Manually maintained JSON Schema
```

source دیگری باشد.

Design:

```text
CommodityAttributeDefinitions
           ↓
     Schema Generator
           ↓
       JSON Schema
           ↓
    Runtime Validation
```

بنابراین relational definitions منبع حقیقت هستند.

JSON Schema derived artifact/runtime representation است.

---

# 18. Backend Validation Must Be Authoritative

Frontend validation صرفاً UX است.

هر specification payload باید در backend نیز با schema version مربوطه validate شود.

Backend باید حداقل موارد زیر را reject کند:

### Wrong type

```json
{
  "softening_point": "hello"
}
```

وقتی type عدد است.

### Missing required field

اگر:

```text
penetration_grade
```

required باشد ولی ارسال نشود.

### Invalid enum

```json
{
  "penetration_grade": "UNKNOWN"
}
```

### Unknown attribute

```json
{
  "magic_field": 123
}
```

وقتی schema چنین keyای ندارد.

Unknown properties باید در حالت عادی **reject** شوند، نه silently persist.

---

# 19. Validation Must Be Schema-Version-aware

Validator نباید فقط Commodity را بگیرد.

Conceptually باید بتواند بگوید:

```text
validate(
    schema_version = Bitumen v1,
    specifications = {...}
)
```

چون later ممکن است:

```text
Bitumen v1
Bitumen v2
```

همزمان historical usage داشته باشند.

Historical data باید با همان schema version اولیه validate/render شود.

---

# 20. Future Domain Integration Contract

Epic 3 هنوز RFQ یا Offer نمی‌سازد، اما قرارداد معماری آن‌ها را مشخص می‌کند.

Future specification-bearing entity:

```text
commodity_id
schema_version_id
specifications JSONB
```

این pattern باید مبنای:

```text
RFQ
Supply Listing
Opportunity
Offer
```

باشد.

---

# 21. Critical Future Invariant — Schema Version Travels With the Record

صرفاً ذخیره این کافی نیست:

```text
commodity = Bitumen
```

هر record باید schema version مربوطه را هم داشته باشد.

زیرا:

```text
Bitumen v1
```

و:

```text
Bitumen v3
```

ممکن است semantics متفاوتی داشته باشند.

بنابراین historical record نباید با active schema امروز reinterpret شود.

---

# 22. Future RFQ → Offer Invariant

اگر RFQ با:

```text
Bitumen Schema v1
```

ایجاد شده باشد، Offerهای پاسخ‌دهنده نیز باید specificationهایشان در context همان schema version قابل مقایسه باشند.

Later architecture:

```text
RFQ Schema Version
        ↓
Offer Validation / Comparison
```

نباید Offer ناگهان از schema version دیگری استفاده کند و semantic comparison را خراب کند.

این rule در Epic 3 باید document شود، هرچند Offer implementation مربوط به Epic بعدی است.

---

# 23. Matching Boundary

Epic 3 semantic data foundation را برای Matching آینده آماده می‌کند.

مثلاً:

```text
RFQ:
penetration_grade = 60_70

Supply:
penetration_grade = 60_70
```

Later Matching Engine می‌تواند اینها را مقایسه کند.

اما Epic 3 نباید implement کند:

```text
matching_score
matching_algorithm
attribute_weight
tolerance_scoring
supplier ranking
AI matching
```

این‌ها concern اپیک Matching هستند.

---

# 24. No Premature Matching Metadata

در Attribute Definition فعلاً metadataهایی مانند:

```text
matching_weight
matching_algorithm
distance_function
score_formula
AI_prompt
ranking_priority
```

نباید اضافه شوند.

Epic 3 فقط تعریف می‌کند:

> Attribute چیست و value معتبر آن چیست؟

نه اینکه در procurement ranking چه وزنی دارد.

---

# 25. No Premature JSONB Indexing

Epic 3 هنوز هیچ business instance واقعی مثل RFQ/Supply/Offer ندارد.

بنابراین نباید برای اثبات JSONB indexing یک generic/fake table ایجاد شود.

JSONB indexing زمانی اضافه می‌شود که اولین real specification-bearing table ساخته شود.

احتمالاً در RFQ / Trade Hub Epic.

Epic 3 باید strategy را documentation کند، ولی index مصنوعی ایجاد نکند.

---

# 26. Bitumen v1 Seed

Epic 3 باید یک deterministic Bitumen schema داشته باشد.

هدف:

* Demo foundation؛
* frontend form demonstration؛
* backend validation proof؛
* basis for upcoming RFQ implementation.

Representative fields می‌توانند شامل موارد زیر باشند:

```text
penetration_grade
penetration
softening_point
ductility
flash_point
solubility
loss_on_heating
```

اما هدف Epic 3 ایجاد database کامل استانداردهای آزمایشگاهی قیر نیست.

Field set باید:

* representative;
* credible;
* sufficient for architecture validation;

باشد.

نباید scope به standardization research عظیم تبدیل شود.

---

# 27. Base Oil Extensibility Proof

Epic باید حداقل Commodity دوم با specification structure متفاوت داشته باشد.

انتخاب پیشنهادی:

```text
Base Oil
```

Representative fields:

```text
base_oil_group
viscosity_at_40c
viscosity_index
flash_point
pour_point
```

هدف Base Oil feature business نیست.

هدفش این سؤال است:

> آیا architecture واقعاً multi-commodity است؟

---

# 28. Critical Extensibility Test

اضافه کردن Base Oil نباید نیازمند موارد زیر باشد:

* Django model مخصوص Base Oil؛
* migration مخصوص specificationهای Base Oil؛
* validator مخصوص Base Oil؛
* React component مخصوص Base Oil؛
* `if commodity == "base_oil"` در generic engine.

Data definition/seed برای Base Oil طبیعتاً وجود خواهد داشت.

اما **engine code نباید Base Oil-specific باشد.**

---

# 29. No Commodity-specific Conditionals

این باید در Codex Review Gate explicitly search شود.

Generic code نباید به شکل زیر باشد:

```python
if commodity.code == "bitumen":
    validate_bitumen(...)
elif commodity.code == "base_oil":
    validate_base_oil(...)
```

یا:

```tsx
if (commodity === "bitumen") {
  return <BitumenForm />;
}
```

اگر چنین logicی برای generic validation/rendering لازم باشد، معماری شکست خورده است.

Commodity differences باید از **data/schema** بیایند.

---

# 30. Seed Strategy

Epic 3 باید deterministic و idempotent initialization برای:

* Bitumen
* Base Oil

داشته باشد.

می‌تواند management command یا روش متناسب با conventions پروژه باشد.

Requirements:

* repeatable؛
* idempotent؛
* بدون duplicate commodity/schema/attributes؛
* بدون overwrite کردن Published historical semantics؛
* suitable for local demo and tests.

نباید generic fixture framework پیچیده ساخته شود.

---

# 31. Commodity Read API

Epic 3 باید حداقل read-only API لازم برای future clients را فراهم کند.

Conceptually:

```http
GET /api/commodities/
```

برای commodity discovery.

مثلاً:

```json
[
  {
    "code": "bitumen",
    "name_fa": "قیر",
    "name_en": "Bitumen"
  }
]
```

و:

```http
GET /api/commodities/{code}/schema/
```

برای active schema.

همچنین historical schema باید قابل retrieval باشد، مثلاً:

```http
GET /api/commodity-schemas/{id}/
```

Exact route naming می‌تواند مطابق project convention نهایی شود.

---

# 32. Historical Schema API Is Important

Frontend later برای نمایش یک RFQ یا Deal قدیمی نباید active schema فعلی را fetch کند.

اگر record با:

```text
schema_version_id = X
```

ذخیره شده، frontend باید بتواند همان X را retrieve کند.

پس historical schema retrieval بخشی از foundation است.

Retired schema نباید حذف یا inaccessible شود صرفاً چون active نیست.

---

# 33. API Scope Is Read-only

در Epic 3 public/product-facing write APIs برای schema management نداریم.

نباید بسازیم:

```http
POST /api/commodities/
POST /api/commodity-schemas/
POST /api/commodity-attributes/
PATCH /api/schema-fields/
```

Schema management فعلاً internal development/admin concern است.

این یک deliberate product decision است.

---

# 34. Django Admin

Django Admin می‌تواند برای internal inspection/configuration استفاده شود.

حداقل باید بتوان:

* Commodityها را دید؛
* Schema Versionها را دید؛
* Attributeها را دید؛
* Draft definitions را مدیریت کرد، اگر implementation ساده و امن است.

اما:

> Published schema باید در admin نیز در برابر semantic mutation محافظت شود.

نباید تنها به UI convention اعتماد کرد؛ domain/service/model-level guard نیز باید وجود داشته باشد.

---

# 35. Dynamic Frontend Form Renderer

Epic 3 باید reusable dynamic form foundation بسازد.

Conceptual component:

```tsx
<CommoditySpecificationForm schema={schema} />
```

این component نباید Commodity-specific knowledge داشته باشد.

Mapping:

```text
string  → Text Input
number  → Numeric Input
integer → Integer Input
boolean → Switch / Checkbox
enum    → Select
```

Renderer باید metadata را مصرف کند:

* localized label
* required
* unit
* enum options
* display group
* sort order
* relevant validation hints

---

# 36. Dynamic Read-only Specification Renderer

علاوه بر Form، reusable display component هم لازم است.

Conceptually:

```tsx
<CommoditySpecificationView
  schema={schema}
  value={specifications}
/>
```

مثلاً:

```text
گرید نفوذ       60/70
نفوذ            65 dmm
نقطه نرمی       49 °C
داکتیلیتی        102 cm
```

این component later در:

* RFQ
* Offer
* Supply
* Opportunity
* Deal

قابل reuse خواهد بود.

---

# 37. UI Invariant

Engine باید generic باشد.

Product experience نباید generic-looking شود.

یعنی:

```text
Dynamic Engine
+
Focused Commodity Procurement UX
```

می‌خواهیم.

نه:

```text
Generic Form Builder Product
```

Bitumen همچنان beachhead/demo commodity اصلی باقی می‌ماند.

---

# 38. Frontend Localization / RTL

Dynamic renderer باید existing Epic 1 localization architecture را حفظ کند.

در demo:

```text
Persian
RTL
```

ولی component باید localized labels را از schema/i18n infrastructure دریافت کند.

نباید داخل generic renderer textهای انگلیسی/فارسی business-specific hard-code شوند.

---

# 39. Backend-authoritative OpenAPI

API همچنان باید invariant قبلی پروژه را رعایت کند:

```text
Django API
    ↓
OpenAPI
    ↓
Generated TypeScript
    ↓
Typed Frontend Client
```

هر endpoint جدید Epic 3 باید در OpenAPI درست represent شود.

Frontend نباید دستی DTOهای Commodity Schema را duplicate کند.

---

# 40. Security Model

Commodity definitions در v1 reference/catalog data هستند.

Read access می‌تواند برای authenticated product users broadly available باشد و اگر Product Spec اجازه دهد حتی later public باشد.

اما Epic 3 نباید write API عمومی بسازد.

Internal definition management:

```text
Django Admin / internal controlled operation
```

است.

Epic 2 authorization architecture نباید bypass شود.

---

# 41. Organization Independence

Commodity Definition به Organization خاصی تعلق ندارد.

مثلاً:

```text
Bitumen
```

یک platform-level reference definition است.

نباید Commodity schema برای هر Buyer/Supplier duplicate شود.

Organization-specific commercial behavior later روی domain entities تعریف می‌شود، نه داخل CommodityDefinition.

---

# 42. Commodity Definition Is Not Inventory

CommodityDefinition فقط نوع و semantics محصول را تعریف می‌کند.

نباید داخل آن مواردی مانند:

```text
supplier
price
available_quantity
inventory
warehouse
delivery terms
```

قرار بگیرد.

این‌ها later concernهای Supply/Trade هستند.

---

# 43. Commodity Definition Is Not RFQ

همین‌طور نباید CommodityDefinition شامل:

```text
requested_quantity
destination
payment_terms
incoterm
delivery_window
target_price
```

باشد.

این‌ها commercial transaction fields هستند.

Commodity schema فقط commodity-specific technical/specification semantics را نگه می‌دارد.

---

# 44. Commodity Definition Is Not Matching Configuration

نباید schema با:

```text
supplier ranking
match score
preferred supplier
commercial weight
price weight
delivery weight
```

آمیخته شود.

Definition Layer باید نسبت به Procurement Decision Engine مستقل بماند.

---

# 45. Schema Validation Service

Backend باید یک reusable API/service-level primitive داشته باشد که بتواند چیزی conceptually شبیه:

```python
validate_specifications(
    schema_version,
    specifications,
)
```

انجام دهد.

این service later توسط:

* RFQ
* Supply Listing
* Opportunity
* Offer

reuse خواهد شد.

نباید validation logic در viewهای Commodity API دفن شود.

---

# 46. Validation Result Semantics

Validation errors باید machine-readable و frontend-friendly باشند.

مثلاً بتوان مشخص کرد:

```text
field:
softening_point

code:
invalid_type
```

یا:

```text
field:
penetration_grade

code:
required
```

لازم نیست error framework بسیار پیچیده ساخته شود، ولی generic `"invalid payload"` برای تمام موارد کافی نیست.

Future forms باید بتوانند error را به field مناسب متصل کنند.

---

# 47. Unknown Fields Policy

Default policy:

> additional/unknown specification fields are rejected.

Reason:

اگر silently بپذیریم:

```json
{
  "softning_point": 49
}
```

یک typo می‌تواند data corruption ایجاد کند.

پس schema باید closed-world باشد مگر later requirement مشخصی خلاف آن ایجاد کند.

---

# 48. Null Semantics

باید distinction مشخص باشد:

```text
optional field missing
```

با:

```text
field explicitly null
```

یکی نیست مگر schema اجازه دهد.

بهتر است validation semantics explicit باشد.

Default پیشنهادی:

* optional → may be absent
* required → must exist
* `null` فقط اگر explicitly supported باشد

نباید هر field غیرrequired خودکار nullable تلقی شود.

---

# 49. Numeric Validation

برای numeric attributes باید بتوان metadataهای ساده‌ای مانند:

```text
minimum
maximum
```

را در صورت نیاز تعریف کرد.

اما Epic 3 نباید تبدیل به full scientific rule engine شود.

مثلاً:

```text
number + min/max
integer + min/max
```

کافی است.

---

# 50. String Validation

برای `string` حداقل basic constraints در صورت نیاز قابل پشتیبانی باشند:

```text
min_length
max_length
```

Regex/custom scripting فقط در صورت نیاز واقعی و با justification.

نباید arbitrary executable validation وارد schema شود.

---

# 51. Enum Validation

Enum option باید:

* canonical value داشته باشد؛
* localized label داشته باشد؛
* deterministic ordering داشته باشد؛
* duplicate canonical values نداشته باشد.

Changing meaning of an existing enum value after publish ممنوع است.

---

# 52. Attribute Ordering / Grouping

برای UI consistency هر Attribute باید بتواند:

```text
sort_order
display_group
```

داشته باشد.

مثلاً:

```text
مشخصات اصلی
مشخصات فنی
```

ولی grouping فقط presentation metadata است.

نباید validation یا business logic به translated group label وابسته شود.

---

# 53. Schema Deletion Policy

Published/historically referenced schema نباید hard-delete شود.

Retirement راه درست lifecycle است.

برای Draft unused schema حذف ممکن است acceptable باشد.

Design باید future historical integrity را در نظر بگیرد.

---

# 54. Attribute Deletion Policy

Attribute متعلق به Published schema نباید delete شود.

در Draft قابل تغییر است.

برای تغییر Published semantics:

> New Schema Version.

---

# 55. No Generic Schema Builder UI

Epic 3 نباید UIای بسازد که Admin بتواند:

* arbitrary form طراحی کند؛
* field drag/drop کند؛
* conditional rules بسازد؛
* formulas بسازد؛
* workflow بسازد؛
* arbitrary nested objects تعریف کند.

این پروژه **commodity procurement infrastructure** است، نه low-code platform.

---

# 56. No Workflow Model in Epic 3

Execution workflows هم later dynamic خواهند بود، اما:

```text
ExecutionWorkflowTemplate
ExecutionMilestoneDefinition
```

متعلق به Epic Execution هستند.

Commodity Schema نباید workflow milestones را نگه دارد.

---

# 57. No AI

در Epic 3 هیچ نیاز به:

* LLM
* AI extraction
* AI classification
* AI matching
* price prediction

وجود ندارد.

Dynamic schema کاملاً deterministic است.

---

# 58. No New Infrastructure

برای Epic 3 نباید به دلیل این feature اضافه کنیم:

* Redis
* Kafka
* RabbitMQ
* Elasticsearch
* Temporal
* Kubernetes
* separate microservice

Django Modular Monolith + PostgreSQL کافی است.

---

# 59. PostgreSQL Is Authoritative

مثل Epicهای قبل:

* migrations باید روی PostgreSQL واقعی تست شوند؛
* SQLite fallback نباید وارد repo شود؛
* constraints باید روی PostgreSQL verify شوند؛
* GitHub CI authoritative intermediate validation است.

Jules sandbox limitation نباید معماری database را تغییر دهد.

---

# 60. Database Constraints

تا جای ممکن integrity واقعی باید در database enforce شود.

حداقل مواردی مانند:

* unique commodity code
* unique `(commodity, schema version)`
* unique `(schema_version, attribute key)`
* lifecycle/data integrity where practical

نباید فقط Django forms مسئول integrity باشند.

هر rule که relational DB می‌تواند منطقی enforce کند باید بررسی شود.

---

# 61. Avoid Overusing Database Constraints

در مقابل، تمام semantic validation dynamic specification را نباید به PostgreSQL CHECKهای پیچیده تبدیل کنیم.

Commodity dynamic validation متعلق به reusable application/schema validation layer است.

DB constraint برای relational integrity.

Dynamic specification schema برای business payload integrity.

این separation باید حفظ شود.

---

# 62. Performance / Query Quality

Epic 3 هنوز high-volume transactional data ندارد.

پس premature optimization نکنیم.

ولی obvious N+1 در:

```text
Commodity
→ Active Schema
→ Attributes
→ Enum Options
```

نباید در API وجود داشته باشد.

Read API باید reasonable eager-loading داشته باشد.

---

# 63. Deterministic Schema Representation

یک Schema Version یک representation deterministic باید داشته باشد.

یعنی دو request برای همان Published schema نباید output semantic متفاوتی بدهند.

Ordering باید stable باشد.

این برای:

* frontend rendering;
* caching later;
* tests;
* comparison;

مهم است.

---

# 64. Stable Historical Rendering

اگر later record به `schema_version_id=X` اشاره کرد:

```text
schema X + specifications
```

باید همیشه همان meaning را render کند.

حتی اگر:

```text
Commodity.active_schema_version = Y
```

شده باشد.

این یکی از دلایل اصلی immutability است.

---

# 65. Schema Cloning / New Version

برای ایجاد v2 لازم نیست sophisticated UI ساخته شود.

ولی implementation بهتر است یک safe domain path داشته باشد که:

```text
Published v1
→ create Draft v2
```

را بدون mutate کردن v1 ممکن کند.

اگر این functionality برای scope زیاد است، حداقل model/service design باید آن را straightforward نگه دارد.

اما هیچ وقت v1 را برای ساخت v2 rewrite نکنیم.

---

# 66. Bitumen Is Beachhead, Not Hard-coded Architecture

Demo و Product Specification فعلی حول Bitumen است.

این کاملاً acceptable است که:

* seed data بیشتر برای Bitumen داشته باشیم؛
* screenshots/demo روی Bitumen باشند؛
* field selection Bitumen realistic باشد.

اما engine code باید commodity-agnostic باشد.

---

# 67. Base Oil Is Architecture Test, Not Product Expansion

Base Oil را نباید تبدیل به Epic business جدید کنیم.

هدف فقط این است:

```text
Can the same system represent a materially different commodity?
```

اگر بله، architecture proof موفق است.

---

# 68. Frontend Dynamicity Test

یک component/code path واحد باید بتواند Bitumen و Base Oil را render کند.

نباید دو component داشته باشیم:

```text
BitumenSpecificationForm
BaseOilSpecificationForm
```

Generic reusable component صحیح است:

```text
CommoditySpecificationForm
```

با schema متفاوت.

---

# 69. Backend Dynamicity Test

یک validator واحد باید هر دو را validate کند.

نباید:

```text
BitumenValidator
BaseOilValidator
```

ساخته شود، مگر later برای استاندارد خاصی واقعاً requirement باشد.

در Epic 3 این کار forbidden است.

---

# 70. Migration Dynamicity Test

مهم‌ترین architecture proof:

بعد از اینکه engine tables ایجاد شدند، اضافه شدن Commodity جدید و Attributeهایش نباید database schema migration بخواهد.

Migration فقط زمانی لازم است که خود engine structure تغییر کند.

نه وقتی:

```text
new commodity
new attribute
new enum option
new schema version
```

اضافه می‌شود.

---

# 71. Epic 3 Read API Expected Functional Flow

Expected demo flow:

```text
GET /api/commodities/
        ↓
Bitumen
Base Oil
        ↓
GET active schema
        ↓
schema attributes
        ↓
frontend generic renderer
        ↓
user enters specifications
        ↓
same schema semantics usable by backend validator
```

فعلاً actual RFQ persistence در این flow وجود ندارد.

---

# 72. No Fake Specification Instance Model

صرفاً برای نمایش JSONB architecture نباید table مصنوعی مانند:

```text
GenericCommoditySpecification
```

بسازیم مگر واقعاً domain meaning داشته باشد.

Actual JSONB instance storage وقتی اولین real business entity ساخته شود اضافه می‌شود.

Epic 3 روی **definition + validation foundation** تمرکز دارد.

---

# 73. Suggested Epic 3 Task Breakdown

## T0301 — Commodity Definition & Schema Models

Implement:

```text
CommodityDefinition
CommoditySchemaVersion
CommodityAttributeDefinition
```

و relational constraints.

---

## T0302 — Schema Lifecycle & Versioning

Implement:

```text
Draft
Published
Retired
active schema
published immutability
ownership integrity
```

---

## T0303 — Dynamic Specification Validation

Implement reusable:

```text
Attribute Definitions
→ generated schema
→ runtime validator
```

و structured validation errors.

---

## T0304 — Bitumen Definition

Seed realistic Bitumen v1.

Verify validation and deterministic schema representation.

---

## T0305 — Secondary Commodity Extensibility Test

Add Base Oil as data.

Prove:

* no model change;
* no specification migration;
* no commodity-specific validator;
* same generic engine.

---

## T0306 — Commodity Read API & OpenAPI

Implement:

```text
commodity list
active schema
historical schema
```

with generated TypeScript contract.

---

## T0307 — Dynamic Specification Form

Generic Persian/RTL frontend renderer.

Support all approved v1 field types.

---

## T0308 — Dynamic Specification View & Epic Integration Tests

Read-only renderer plus final cross-commodity architecture validation.

---

# 74. Definition of Done

Epic 3 is successful only if we can demonstrate the following:

Create a new Commodity definition with fields materially different from Bitumen.

Then, **without changing Django domain models and without creating a specification-field migration**:

```text
Backend
→ can expose its schema

Frontend
→ can render its form

Frontend
→ can display values

Backend validator
→ accepts valid payload

Backend validator
→ rejects invalid payload

Historical schema
→ remains retrievable

Published previous version
→ remains unchanged
```

---

# 75. Epic Failure Conditions

Epic 3 should be considered architecturally failed if any of these are necessary:

```python
if commodity == "bitumen":
```

inside generic validation/rendering.

Or:

```python
class BitumenRFQ(...)
```

for basic specification support.

Or adding:

```text
softening_point
penetration
viscosity_index
```

columns to generic core models.

Or modifying Published schema in place.

Or allowing historical records to use today's active schema instead of their original version.

Or treating frontend validation as authoritative.

---

# 76. Required Epic 3 Review Gate Checks

Codex Review Gate should explicitly verify:

### Domain Model

* CommodityDefinition is generic.
* CommoditySchemaVersion is properly versioned.
* Attribute Definition belongs to schema version.
* relational uniqueness constraints exist.
* no commodity-specific core columns exist.

### Lifecycle

* Draft mutable.
* Published immutable.
* Retired remains readable.
* active schema belongs to correct Commodity.
* active schema uses valid lifecycle state.

### Validation

* required fields.
* optional fields.
* null behavior.
* unknown field rejection.
* type validation.
* enum validation.
* numeric constraints.
* deterministic errors.
* schema-version-aware validation.

### Extensibility

* Bitumen and Base Oil use exactly the same engine.
* no commodity-specific conditional code.
* adding Commodity data requires no schema-field migration.

### API

* commodity list works.
* active schema works.
* historical schema works.
* inactive/retired behavior intentional.
* OpenAPI accurate.
* generated TypeScript drift-free.

### Frontend

* same component renders both Commodities.
* all approved types render.
* labels localized.
* RTL preserved.
* unit/required/enum metadata displayed correctly.
* no manually duplicated DTOs.

### PostgreSQL

* fresh migrations.
* constraints.
* no SQLite fallback.
* idempotent seeds.
* duplicate definitions rejected where expected.

### Regression

* Epic 1 platform remains healthy.
* Epic 2 authentication/authorization remains healthy.
* CI remains green.
* no new security bypass.

### Scope

* no RFQ.
* no Offer.
* no Supply Listing.
* no Opportunity.
* no Matching.
* no Schema Builder.
* no AI.
* no new infrastructure.

---

# 77. Long-term Architectural Contract Created by Epic 3

بعد از Epic 3، تمام Epicهای بعدی باید این contract را رعایت کنند:

```text
Commodity semantics
        ↓
Versioned Commodity Schema
        ↓
Dynamic Specification Payload
        ↓
RFQ / Supply / Opportunity / Offer
```

و:

```text
Schema Version at creation time
        ↓
remains attached to business record
        ↓
historical meaning remains stable forever
```

این پایه later امکان:

* structured matching;
* offer comparison;
* procurement analytics;
* supplier performance;
* market intelligence;

را فراهم می‌کند.

---

# 78. Final Architectural Statement

Epic 3 نباید صرفاً «چند مدل برای Commodity» بسازد.

خروجی واقعی Epic باید یک contract پایدار باشد:

> **Commodity-specific knowledge lives in versioned data definitions, while the application engine remains commodity-agnostic.**

Definitionها:

```text
Relational
Versioned
Localized
Controlled
```

Instance specifications:

```text
Dynamic
Schema-bound
Future JSONB
```

Published semantics:

```text
Immutable
Historically reproducible
```

Frontend/backend:

```text
Schema-driven
Backend-authoritative
Commodity-agnostic
```

Product:

```text
Bitumen-focused
Multi-commodity-ready
Not a generic low-code platform
```

اگر این چهار اصل تا پایان Epic حفظ شوند، foundation ما برای RFQ، Supply، Opportunity، Offers و Matching آماده است.
