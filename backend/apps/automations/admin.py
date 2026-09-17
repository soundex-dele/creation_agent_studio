from django.contrib import admin

from .models import Automation, AutomationInvocation


admin.site.register(Automation)
admin.site.register(AutomationInvocation)
