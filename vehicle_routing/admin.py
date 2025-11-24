from django.contrib import admin
from .models import VRPSolution, VRPConfiguration

class VRPSolutionAdmin(admin.ModelAdmin):
    list_display = ('id', 'solution_id', 'created_at')
    search_fields = ('solution_id',)
    list_filter = ('created_at',)

# Register your models here.
admin.site.register(VRPSolution, VRPSolutionAdmin)
admin.site.register(VRPConfiguration)