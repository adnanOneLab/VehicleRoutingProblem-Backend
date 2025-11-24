from rest_framework import serializers
from .models import VRPConfiguration, VRPSolution

class VRPConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = VRPConfiguration
        fields = ['id', 'name', 'description', 'config_data', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class VRPSolutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VRPSolution
        fields = ['id', 'solution_id', 'input_data', 'solution_data', 'created_at']
        read_only_fields = ['id', 'created_at']