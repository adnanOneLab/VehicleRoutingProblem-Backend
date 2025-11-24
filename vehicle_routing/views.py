from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache
from django.conf import settings
import json
import uuid
import requests
from .vrp_solver import solve_vrp_problem
from .pdp_solver import solve_pdp_problem
from .models import VRPConfiguration, VRPSolution
from .serializers import VRPConfigSerializer, VRPSolutionSerializer

@api_view(['POST'])
def solve_vrp(request):
    """
    Solve Vehicle Routing Problem with the provided data
    """
    try:
        vrp_data = request.data
        
        # Validate required fields
        required_fields = ['distance_matrix', 'time_windows', 'demands', 
                          'vehicle_capacities', 'num_vehicles', 'depot']
        
        for field in required_fields:
            if field not in vrp_data:
                return Response(
                    {'error': f'Missing required field: {field}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Validate time windows before solving
        time_window_errors = []
        for i, tw in enumerate(vrp_data.get('time_windows', [])):
            if len(tw) != 2:
                time_window_errors.append(f'Time window {i} must have [start, end] format')
            elif tw[0] > tw[1]:
                location_name = vrp_data.get('locations', [{}])[i].get('name', f'Location {i}')
                time_window_errors.append(f'{location_name}: Start time ({tw[0]} min) is after end time ({tw[1]} min)')
        
        if time_window_errors:
            return Response(
                {'error': 'Invalid time windows:\n' + '\n'.join(time_window_errors)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Solve the VRP problem
        solution = solve_vrp_problem(vrp_data)
        
        if solution is None:
            # Provide more helpful error message
            error_msg = (
                'No solution found for the given constraints. '
                'Common causes:\n'
                '- Time windows are too restrictive or conflict with travel times\n'
                '- Not enough vehicles for the number of locations\n'
                '- Capacity constraints cannot be satisfied\n'
                'Try widening time windows, adding more vehicles, or increasing capacity.'
            )
            return Response(
                {'error': error_msg}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate solution ID
        solution_id = str(uuid.uuid4())
        
        # Cache the solution for 1 hour (optional - doesn't fail if Redis unavailable)
        try:
            cache.set(f'vrp_solution_{solution_id}', solution, 3600)
        except Exception:
            # Cache unavailable - continue without caching
            pass
        
        # Optionally save to database
        if request.data.get('save_solution', False):
            VRPSolution.objects.create(
                solution_id=solution_id,
                input_data=vrp_data,
                solution_data=solution
            )
        
        return Response({
            'solution_id': solution_id,
            'solution': solution,
            'status': 'success'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response(
            {'error': str(e), 'details': 'Internal server error'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_vrp_solution(request, solution_id):
    """
    Retrieve a VRP solution by ID
    """
    try:
        solution = None
        
        # Try cache first (optional - doesn't fail if Redis unavailable)
        try:
            solution = cache.get(f'vrp_solution_{solution_id}')
        except Exception:
            # Cache unavailable - continue to database lookup
            pass
        
        # If not in cache, try database
        if solution is None:
            try:
                vrp_solution = VRPSolution.objects.get(
                    solution_id=solution_id
                )
                solution = vrp_solution.solution_data
            except VRPSolution.DoesNotExist:
                return Response(
                    {'error': 'Solution not found'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        
        return Response({
            'solution_id': solution_id,
            'solution': solution
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def save_vrp_config(request):
    """
    Save VRP configuration for later use
    """
    try:
        config_data = request.data
        
        serializer = VRPConfigSerializer(data=config_data)
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    except Exception as e:
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def get_vrp_configs(request):
    """
    Get all saved VRP configurations for the user
    """
    try:
        configs = VRPConfiguration.objects.all()
        serializer = VRPConfigSerializer(configs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
def delete_vrp_config(request, config_id):
    """
    Delete a VRP configuration
    """
    try:
        config = VRPConfiguration.objects.get(id=config_id)
        config.delete()
        return Response(
            {'message': 'Configuration deleted successfully'}, 
            status=status.HTTP_200_OK
        )
        
    except VRPConfiguration.DoesNotExist:
        return Response(
            {'error': 'Configuration not found'}, 
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def validate_vrp(request):
    """
    Validate VRP data before solving
    """
    try:
        vrp_data = request.data
        errors = []
        warnings = []
        
        # Check matrix dimensions
        n_locations = len(vrp_data.get('distance_matrix', []))
        
        if n_locations != len(vrp_data.get('time_windows', [])):
            errors.append('Number of time windows must match number of locations')
        
        if n_locations != len(vrp_data.get('demands', [])):
            errors.append('Number of demands must match number of locations')
        
        # Check if distance matrix is square
        for row in vrp_data.get('distance_matrix', []):
            if len(row) != n_locations:
                errors.append('Distance matrix must be square')
                break
        
        # Check capacity vs demand
        total_capacity = sum(vrp_data.get('vehicle_capacities', []))
        total_demand = sum([abs(d) for d in vrp_data.get('demands', [])])
        
        if total_capacity < total_demand:
            warnings.append(f'Total capacity ({total_capacity}) is less than total demand ({total_demand})')
        
        # Check time windows
        for i, tw in enumerate(vrp_data.get('time_windows', [])):
            if tw[0] > tw[1]:
                errors.append(f'Invalid time window at location {i}: start > end')
        
        if errors:
            return Response({
                'valid': False,
                'errors': errors,
                'warnings': warnings
            }, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'valid': True,
            'warnings': warnings
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def solve_pdp(request):
    """
    Solve Pickup and Delivery Problem (PDP) with transfer requests
    Expected data format:
    {
        'locations': [{'id': 0, 'name': 'Hotel A', 'lat': ..., 'lng': ...}, ...],
        'vehicles': [
            {'id': 0, 'capacity': 10, 'start_location': 2, 'start_time': 480},
            ...
        ],
        'transfer_requests': [
            {
                'id': 0,
                'pickup_location': 1,
                'delivery_location': 2,
                'passengers': 4,
                'arrival_time_at_pickup': 600,
                'pickup_time_window': [600, 720],
                'delivery_time_window': [720, 900]  # optional
            },
            ...
        ],
        'distance_matrix': [[...], ...],  # Optional, will be calculated if not provided
        'time_matrix': [[...], ...]  # Optional
    }
    """
    try:
        pdp_data = request.data
        
        # Validate required fields
        required_fields = ['locations', 'vehicles', 'transfer_requests']
        for field in required_fields:
            if field not in pdp_data:
                return Response(
                    {'error': f'Missing required field: {field}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # If distance_matrix not provided, calculate from locations
        if 'distance_matrix' not in pdp_data or not pdp_data['distance_matrix']:
            # Calculate using Haversine formula
            from math import sin, cos, atan2, sqrt, radians
            locations = pdp_data['locations']
            num_locations = len(locations)
            distance_matrix = []
            
            for i in range(num_locations):
                row = []
                for j in range(num_locations):
                    if i == j:
                        row.append(0)
                    else:
                        lat1, lng1 = locations[i]['lat'], locations[i]['lng']
                        lat2, lng2 = locations[j]['lat'], locations[j]['lng']
                        R = 6371  # Earth's radius in km
                        dlat = radians(lat2 - lat1)
                        dlng = radians(lng2 - lng1)
                        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
                        c = 2 * atan2(sqrt(a), sqrt(1-a))
                        distance = round(R * c)
                        row.append(distance)
                distance_matrix.append(row)
            
            pdp_data['distance_matrix'] = distance_matrix
        
        # Solve the PDP problem
        solution = solve_pdp_problem(pdp_data)
        
        if solution is None:
            return Response(
                {'error': 'No solution found. Check time windows, capacities, and transfer request constraints.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Generate solution ID
        solution_id = str(uuid.uuid4())
        
        # Cache the solution
        try:
            cache.set(f'pdp_solution_{solution_id}', solution, 3600)
        except Exception:
            pass
        
        # Optionally save to database
        if request.data.get('save_solution', False):
            VRPSolution.objects.create(
                solution_id=solution_id,
                input_data=pdp_data,
                solution_data=solution
            )
        
        return Response({
            'solution_id': solution_id,
            'solution': solution,
            'status': 'success'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response(
            {'error': str(e), 'details': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def google_maps_distance_matrix(request):
    """
    Get distance matrix from Google Maps Distance Matrix API via backend
    This avoids CORS issues when calling from frontend
    """
    try:
        locations = request.data.get('locations', [])
        
        if not locations:
            return Response(
                {'error': 'No locations provided'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if Google Maps API key is configured
        google_maps_api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', None)
        if not google_maps_api_key:
            # Try environment variable
            import os
            google_maps_api_key = os.getenv('GOOGLE_MAPS_API_KEY')
        
        if not google_maps_api_key:
            return Response(
                {'error': 'Google Maps API key not configured. Set GOOGLE_MAPS_API_KEY in backend .env file'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Format locations for Google Maps API
        origins = '|'.join([f"{loc['lat']},{loc['lng']}" for loc in locations])
        destinations = origins  # Same locations
        
        # Call Google Maps Distance Matrix API
        url = 'https://maps.googleapis.com/maps/api/distancematrix/json'
        params = {
            'origins': origins,
            'destinations': destinations,
            'departure_time': 'now',
            'traffic_model': 'best_guess',
            'units': 'metric',
            'key': google_maps_api_key
        }
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        # Check for API errors
        if data.get('status') != 'OK':
            error_msg = data.get('error_message', f"API returned status: {data.get('status')}")
            return Response(
                {'error': f'Google Maps API error: {error_msg}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Convert to distance matrix format
        matrix = []
        for i, row in enumerate(data.get('rows', [])):
            matrix_row = []
            for j, element in enumerate(row.get('elements', [])):
                if i == j:
                    matrix_row.append(0)
                elif element.get('status') == 'OK':
                    # Return distance in km
                    distance_km = round(element['distance']['value'] / 1000)
                    matrix_row.append(distance_km)
                else:
                    # Fallback: calculate Haversine distance
                    from math import sin, cos, atan2, sqrt, radians
                    R = 6371  # Earth's radius in km
                    lat1, lng1 = locations[i]['lat'], locations[i]['lng']
                    lat2, lng2 = locations[j]['lat'], locations[j]['lng']
                    dlat = radians(lat2 - lat1)
                    dlng = radians(lng2 - lng1)
                    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
                    c = 2 * atan2(sqrt(a), sqrt(1-a))
                    distance = round(R * c)
                    matrix_row.append(distance)
            matrix.append(matrix_row)
        
        return Response({
            'distance_matrix': matrix,
            'status': 'success'
        }, status=status.HTTP_200_OK)
        
    except requests.exceptions.RequestException as e:
        return Response(
            {'error': f'Network error calling Google Maps API: {str(e)}'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )