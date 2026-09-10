from django.contrib.auth.hashers import check_password, make_password
from django.db import migrations


def retire_shared_demo_password(apps, schema_editor):
    User = apps.get_model("identity", "User")
    personas = ("buyer", "supplier", "broker", "operator", "admin")
    users = User.objects.using(schema_editor.connection.alias).filter(
        email__in=[f"{persona}@demo.local" for persona in personas]
    )
    for user in users.iterator():
        # This was the public seed password; never restore it on reversal.
        if check_password("demo1234", user.password):
            user.password = make_password(None)
            user.save(using=schema_editor.connection.alias, update_fields=["password"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0002_systemroleassignment")]

    operations = [
        migrations.RunPython(retire_shared_demo_password, migrations.RunPython.noop),
    ]
