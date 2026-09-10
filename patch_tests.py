import re

with open('apps/api/commodities/tests.py', 'r') as f:
    content = f.read()

# Fix module level imports
# Find the imports that need to be moved
imports_to_move = """
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from identity.models import User
"""

# Extract the imports from the end and put them at the top
content = content.replace(imports_to_move.strip() + "\n", "")

# Remove duplicate model imports
content = content.replace("from .models import CommodityDefinition, CommoditySchemaVersion, CommodityAttributeDefinition", "")
# Re-add it at the top where it belongs if it's missing (it's actually at line 4 already)

# Actually, the best way is just to manually fix tests.py
