from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import logging

logger = logging.getLogger(__name__)

def solve_vrp_problem(data):
    """
    Solve VRP problem using OR-Tools with improved time handling and search strategies
    
    Improvements:
    - Separate time callback (converts distance to time)
    - Better search strategy (AUTOMATIC)
    - Local search improvement (GUIDED_LOCAL_SEARCH)
    - Support for time_matrix if provided
    - Service time support
    
    Returns solution dictionary or None if no solution found
    """
    try:
        # Create the routing index manager
        manager = pywrapcp.RoutingIndexManager(
            len(data['distance_matrix']),
            data['num_vehicles'],
            data['depot']
        )
        
        # Create Routing Model
        routing = pywrapcp.RoutingModel(manager)
        
        # Create and register distance callback (for cost optimization)
        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return data['distance_matrix'][from_node][to_node]
        
        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        
        # CRITICAL FIX: Create separate time callback
        # Time windows need travel TIME, not distance
        # If time_matrix is provided, use it; otherwise convert distance to time
        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            
            # Use time_matrix if provided (from Google Maps with duration)
            if 'time_matrix' in data and data['time_matrix']:
                return data['time_matrix'][from_node][to_node]
            
            # Otherwise, convert distance to time
            # Assume average speed of 50 km/h = 0.833 km/min
            distance_km = data['distance_matrix'][from_node][to_node]
            time_minutes = int(distance_km / 0.833) if distance_km > 0 else 0
            
            # Add service time if specified (time spent at location)
            service_time = data.get('service_times', [0] * len(data['distance_matrix']))
            if from_node < len(service_time):
                time_minutes += service_time[from_node]
            
            return time_minutes
        
        time_callback_index = routing.RegisterTransitCallback(time_callback)
        
        # Create and register demand callback
        def demand_callback(from_index):
            from_node = manager.IndexToNode(from_index)
            return data['demands'][from_node]
        
        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        
        # Add capacity constraint
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index,
            0,  # null capacity slack
            data['vehicle_capacities'],
            True,  # start cumul to zero
            'Capacity'
        )
        
        # Calculate max time needed (find latest time window end + buffer)
        # Time windows are in minutes from start of day (0 = midnight)
        max_time_window = max([tw[1] for tw in data['time_windows']], default=1440)  # Default to 24 hours
        max_route_time = max_time_window + 120  # Add 2 hours buffer for travel
        
        # CRITICAL FIX: Use time_callback_index instead of transit_callback_index
        # Add time dimension (in minutes) - NOW USES TIME, NOT DISTANCE
        routing.AddDimension(
            time_callback_index,  # FIXED: Use time callback, not distance
            30,  # allow waiting time (30 minutes max wait at location)
            max_route_time,  # maximum time per vehicle route (in minutes)
            False,  # Don't force start cumul to zero
            'Time'
        )
        
        # Add time window constraints
        time_dimension = routing.GetDimensionOrDie('Time')
        for location_idx, time_window in enumerate(data['time_windows']):
            if location_idx == data['depot']:
                # Depot can be visited anytime, but let's set reasonable bounds
                index = manager.NodeToIndex(location_idx)
                time_dimension.CumulVar(index).SetRange(0, max_route_time)
                continue
            
            index = manager.NodeToIndex(location_idx)
            # time_window is [start_minutes, end_minutes]
            time_dimension.CumulVar(index).SetRange(time_window[0], time_window[1])
        
        # IMPROVEMENT: Better search parameters
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        
        # Use AUTOMATIC strategy - OR-Tools will choose the best strategy
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.AUTOMATIC
        )
        
        # IMPROVEMENT: Add local search for better solutions
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        
        # Increase time limit for better solutions (was 30, now 60 seconds)
        search_parameters.time_limit.seconds = 60
        
        # Try multiple solutions for better quality
        search_parameters.solution_limit = 100
        
        # Solve the problem
        solution = routing.SolveWithParameters(search_parameters)
        
        if solution:
            # Get the routing status
            routing_status = routing.status()
            logger.info(f"VRP solved successfully. Status: {routing_status}")
            return format_solution(data, manager, routing, solution, routing_status)
        else:
            logger.warning("No solution found for VRP problem")
            return None
            
    except Exception as e:
        logger.error(f"Error solving VRP: {str(e)}", exc_info=True)
        return None


def format_solution(data, manager, routing, solution, routing_status):
    """
    Format the OR-Tools solution into a JSON-friendly structure
    """
    time_dimension = routing.GetDimensionOrDie('Time')
    total_distance = 0
    routes = []
    
    for vehicle_id in range(data['num_vehicles']):
        index = routing.Start(vehicle_id)
        route = {
            'vehicle_id': vehicle_id,
            'stops': [],
            'total_distance': 0,
            'total_time': 0,
            'total_load': 0
        }
        
        route_distance = 0
        route_time = 0
        
        while not routing.IsEnd(index):
            time_var = time_dimension.CumulVar(index)
            node_index = manager.IndexToNode(index)
            
            arrival_time = solution.Min(time_var)
            departure_time = solution.Max(time_var)
            
            stop = {
                'location_index': node_index,
                'location_name': data.get('locations', [{}])[node_index].get('name', f'Location {node_index}'),
                'arrival_time': arrival_time,
                'departure_time': departure_time,
                'wait_time': max(0, departure_time - arrival_time),  # Time spent waiting
                'load': data['demands'][node_index],
                'cumulative_load': 0
            }
            
            route['stops'].append(stop)
            
            previous_index = index
            index = solution.Value(routing.NextVar(index))
            
            # Calculate distance for this arc
            route_distance += routing.GetArcCostForVehicle(
                previous_index, index, vehicle_id
            )
            
            # Calculate time for this arc
            if not routing.IsEnd(index):
                route_time += time_dimension.GetTransitValue(
                    previous_index, index, vehicle_id
                )
        
        # Add final depot stop
        time_var = time_dimension.CumulVar(index)
        route['stops'].append({
            'location_index': manager.IndexToNode(index),
            'location_name': 'Depot',
            'arrival_time': solution.Min(time_var),
            'departure_time': solution.Max(time_var),
            'wait_time': 0,
            'load': 0,
            'cumulative_load': 0
        })
        
        route['total_distance'] = route_distance
        route['total_time'] = route_time
        total_distance += route_distance
        
        # Calculate cumulative load
        cumulative = 0
        for stop in route['stops']:
            cumulative += stop['load']
            stop['cumulative_load'] = cumulative
        
        routes.append(route)
    
    # Map routing status to string
    status_map = {
        0: 'not_solved',
        1: 'optimal',  # ROUTING_SUCCESS
        2: 'no_solution',  # ROUTING_FAIL
        3: 'timeout',  # ROUTING_FAIL_TIMEOUT
        4: 'invalid'  # ROUTING_INVALID
    }
    
    status_str = status_map.get(routing_status, 'feasible')
    
    return {
        'objective_value': solution.ObjectiveValue(),
        'total_distance': total_distance,
        'routes': routes,
        'status': status_str
    }

