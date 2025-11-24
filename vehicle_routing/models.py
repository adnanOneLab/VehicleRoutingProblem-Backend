from django.db import models
from django.conf import settings

class VRPConfiguration(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    config_data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name}"


class VRPSolution(models.Model):
    solution_id = models.CharField(max_length=255, unique=True)
    input_data = models.JSONField()
    solution_data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Solution {self.solution_id}"