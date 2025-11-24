from ortools.constraint_solver import pywrapcp, routing_enums_pb2

def solve_vrp_problem(data):
    """
    Solve VRP problem using OR-Tools
    Supports:
    - Multiple depots (if vehicle_starts provided)
    - Pickup and delivery constraints (if pickup_delivery_pairs provided)
    
    Returns solution dictionary or None if no solution found
    """
    try:
        num_nodes = len(data['distance_matrix'])
        num_vehicles = data['num_vehicles']
        
        # Support multiple depots: if vehicle_starts provided, use it
        # Otherwise, use single depot
        if 'vehicle_starts' in data and data['vehicle_starts']:
            vehicle_starts = data['vehicle_starts']
            vehicle_ends = data.get('vehicle_ends', vehicle_starts)  # Default to same as starts
            # Ensure we have starts/ends for all vehicles
            while len(vehicle_starts) < num_vehicles:
                vehicle_starts.append(data.get('depot', 0))
            while len(vehicle_ends) < num_vehicles:
                vehicle_ends.append(vehicle_starts[len(vehicle_ends)] if len(vehicle_ends) < len(vehicle_starts) else data.get('depot', 0))
            
            manager = pywrapcp.RoutingIndexManager(
                num_nodes,
                num_vehicles,
                vehicle_starts,
                vehicle_ends
            )
        else:
            # Single depot (original behavior)
            depot = data.get('depot', 0)
            manager = pywrapcp.RoutingIndexManager(
                num_nodes,
                num_vehicles,
                depot
            )
        
        # Create Routing Model
        routing = pywrapcp.RoutingModel(manager)
        
        # Create and register distance callback
        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return data['distance_matrix'][from_node][to_node]
        
        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        
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
        
        # Create time callback (convert distance to time if time_matrix not provided)
        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            
            # Use time_matrix if provided
            if 'time_matrix' in data and data['time_matrix']:
                return data['time_matrix'][from_node][to_node]
            
            # Otherwise, convert distance to time (assume 50 km/h = 0.833 km/min)
            distance_km = data['distance_matrix'][from_node][to_node]
            time_minutes = int(distance_km / 0.833) if distance_km > 0 else 0
            
            # Add service time (5 minutes at each stop)
            service_time = data.get('service_times', [5] * len(data['distance_matrix']))
            if from_node < len(service_time):
                time_minutes += service_time[from_node] if isinstance(service_time, list) else service_time
            
            return time_minutes
        
        time_callback_index = routing.RegisterTransitCallback(time_callback)
        
        # Add time dimension (in minutes) - NOW USES TIME, NOT DISTANCE
        routing.AddDimension(
            time_callback_index,  # Use time callback, not distance
            30,  # allow waiting time (30 minutes max wait at location)
            max_route_time,  # maximum time per vehicle route (in minutes)
            False,  # Don't force start cumul to zero
            'Time'
        )
        
        # Add pickup and delivery constraints if provided
        if 'pickup_delivery_pairs' in data and data['pickup_delivery_pairs']:
            for pickup_node, delivery_node in data['pickup_delivery_pairs']:
                pickup_index = manager.NodeToIndex(pickup_node)
                delivery_index = manager.NodeToIndex(delivery_node)
                routing.AddPickupAndDelivery(pickup_index, delivery_index)
                # Same vehicle must handle both pickup and delivery
                routing.solver().Add(
                    routing.VehicleVar(pickup_index) == routing.VehicleVar(delivery_index)
                )
        
        # Add time window constraints
        time_dimension = routing.GetDimensionOrDie('Time')
        
        # Handle vehicle start times if provided
        vehicle_start_times = data.get('vehicle_start_times', [0] * num_vehicles)
        for vehicle_id in range(num_vehicles):
            start_index = routing.Start(vehicle_id)
            start_time = vehicle_start_times[vehicle_id] if vehicle_id < len(vehicle_start_times) else 0
            time_dimension.CumulVar(start_index).SetRange(start_time, max_route_time)
        
        for location_idx, time_window in enumerate(data['time_windows']):
            # Skip if this is a depot and we're using multiple depots
            if 'vehicle_starts' in data and data['vehicle_starts']:
                # In multi-depot mode, don't skip any nodes
                pass
            elif location_idx == data.get('depot', 0):
                # Single depot mode: depot can be visited anytime
                index = manager.NodeToIndex(location_idx)
                time_dimension.CumulVar(index).SetRange(0, max_route_time)
                continue
            
            index = manager.NodeToIndex(location_idx)
            # time_window is [start_minutes, end_minutes]
            time_dimension.CumulVar(index).SetRange(time_window[0], time_window[1])
        
        # Set search parameters
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_parameters.time_limit.seconds = 30
        
        # Solve the problem
        solution = routing.SolveWithParameters(search_parameters)
        
        if solution:
            # Get the routing status
            routing_status = routing.status()
            return format_solution(data, manager, routing, solution, routing_status)
        else:
            return None
            
    except Exception as e:
        print(f"Error solving VRP: {str(e)}")
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
            'total_load': 0
        }
        
        route_distance = 0
        
        while not routing.IsEnd(index):
            time_var = time_dimension.CumulVar(index)
            node_index = manager.IndexToNode(index)
            
            stop = {
                'location_index': node_index,
                'location_name': data.get('locations', [{}])[node_index].get('name', f'Location {node_index}'),
                'arrival_time': solution.Min(time_var),
                'departure_time': solution.Max(time_var),
                'load': data['demands'][node_index],
                'cumulative_load': 0
            }
            
            route['stops'].append(stop)
            
            previous_index = index
            index = solution.Value(routing.NextVar(index))
            route_distance += routing.GetArcCostForVehicle(
                previous_index, index, vehicle_id
            )
        
        # Add final depot stop
        time_var = time_dimension.CumulVar(index)
        route['stops'].append({
            'location_index': manager.IndexToNode(index),
            'location_name': 'Depot',
            'arrival_time': solution.Min(time_var),
            'departure_time': solution.Max(time_var),
            'load': 0,
            'cumulative_load': 0
        })
        
        route['total_distance'] = route_distance
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