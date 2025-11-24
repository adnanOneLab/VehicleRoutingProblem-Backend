from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import logging

logger = logging.getLogger(__name__)

def solve_pdp_problem(data):
    """
    Solve Pickup and Delivery Problem (PDP) with multiple depots using OR-Tools
    
    Data structure expected:
    {
        'distance_matrix': [[...], ...],  # Distance between all locations
        'time_matrix': [[...], ...] or None,  # Travel time between locations (optional)
        'locations': [{'id': 0, 'name': 'Hotel A', 'lat': ..., 'lng': ...}, ...],
        'vehicles': [
            {
                'id': 0,
                'capacity': 10,
                'start_location': 2,  # Can start at any location (hotel, airport, etc.)
                'start_time': 480  # Start time in minutes (optional, default 0)
            },
            ...
        ],
        'transfer_requests': [
            {
                'id': 0,
                'pickup_location': 1,  # Source location index
                'delivery_location': 2,  # Destination location index
                'passengers': 4,  # Number of people
                'arrival_time_at_pickup': 600,  # When passengers arrive at pickup location (minutes)
                'pickup_time_window': [600, 720],  # Time window for pickup [start, end]
                'delivery_time_window': [720, 900]  # Time window for delivery [start, end] (optional)
            },
            ...
        ]
    }
    """
    try:
        num_locations = len(data['distance_matrix'])
        num_vehicles = len(data['vehicles'])
        transfer_requests = data['transfer_requests']
        
        # For PDP, we need to create pickup and delivery nodes
        # Each transfer request becomes 2 nodes: pickup node and delivery node
        # Total nodes = num_locations (existing) + 2 * num_requests (pickup + delivery for each)
        
        # Create mapping: request_id -> (pickup_node_index, delivery_node_index)
        # Pickup nodes start after original locations
        # Delivery nodes start after pickup nodes
        request_to_nodes = {}
        node_to_request = {}  # Maps node index to request info
        node_to_location = {}  # Maps node index to original location index
        
        # First, map original locations
        for loc_idx in range(num_locations):
            node_to_location[loc_idx] = loc_idx
        
        # Add pickup and delivery nodes for each request
        current_node = num_locations
        for req in transfer_requests:
            pickup_node = current_node
            delivery_node = current_node + 1
            current_node += 2
            
            request_to_nodes[req['id']] = (pickup_node, delivery_node)
            node_to_request[pickup_node] = {
                'type': 'pickup',
                'request_id': req['id'],
                'location': req['pickup_location'],
                'passengers': req['passengers']
            }
            node_to_request[delivery_node] = {
                'type': 'delivery',
                'request_id': req['id'],
                'location': req['delivery_location'],
                'passengers': -req['passengers']  # Negative for delivery
            }
            node_to_location[pickup_node] = req['pickup_location']
            node_to_location[delivery_node] = req['delivery_location']
        
        total_nodes = current_node
        
        # Build extended distance matrix (includes pickup/delivery nodes at same locations)
        extended_distance_matrix = []
        for i in range(total_nodes):
            row = []
            for j in range(total_nodes):
                loc_i = node_to_location[i]
                loc_j = node_to_location[j]
                # Distance between nodes at same location is 0
                if i == j:
                    row.append(0)
                elif loc_i == loc_j:
                    row.append(0)  # Same physical location
                else:
                    row.append(data['distance_matrix'][loc_i][loc_j])
            extended_distance_matrix.append(row)
        
        # Build extended time matrix if provided
        extended_time_matrix = None
        if data.get('time_matrix'):
            extended_time_matrix = []
            for i in range(total_nodes):
                row = []
                for j in range(total_nodes):
                    loc_i = node_to_location[i]
                    loc_j = node_to_location[j]
                    if i == j:
                        row.append(0)
                    elif loc_i == loc_j:
                        row.append(0)
                    else:
                        row.append(data['time_matrix'][loc_i][loc_j])
                extended_time_matrix.append(row)
        
        # Create routing index manager with multiple depots
        # For multiple depots, we need to create start/end nodes for each vehicle
        # OR-Tools supports this by using different start/end indices
        
        # Get start locations for each vehicle (these are location indices, which are also node indices for original locations)
        vehicle_starts = [v['start_location'] for v in data['vehicles']]
        vehicle_ends = vehicle_starts  # Vehicles can end at their start location
        
        # Validate start locations
        for i, start_loc in enumerate(vehicle_starts):
            if start_loc < 0 or start_loc >= num_locations:
                raise ValueError(f"Vehicle {i} has invalid start_location {start_loc}. Must be between 0 and {num_locations-1}")
        
        # Create manager with multiple depots
        # RoutingIndexManager(num_nodes, num_vehicles, starts, ends)
        # starts and ends are lists of node indices where each vehicle starts/ends
        manager = pywrapcp.RoutingIndexManager(
            total_nodes,
            num_vehicles,
            vehicle_starts,  # Start node indices for each vehicle (location indices for original locations)
            vehicle_ends     # End node indices for each vehicle
        )
        
        routing = pywrapcp.RoutingModel(manager)
        
        # Distance callback
        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return extended_distance_matrix[from_node][to_node]
        
        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        
        # Time callback
        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            
            if extended_time_matrix:
                time = extended_time_matrix[from_node][to_node]
            else:
                # Convert distance to time (assume 50 km/h = 0.833 km/min)
                distance_km = extended_distance_matrix[from_node][to_node]
                time = int(distance_km / 0.833) if distance_km > 0 else 0
            
            # Add service time (5 minutes at each stop)
            if from_node < num_locations:
                time += 5  # Service time at original locations
            else:
                time += 3  # Service time at pickup/delivery nodes
            
            return time
        
        time_callback_index = routing.RegisterTransitCallback(time_callback)
        
        # Demand callback (for capacity)
        def demand_callback(from_index):
            from_node = manager.IndexToNode(from_index)
            if from_node in node_to_request:
                return node_to_request[from_node]['passengers']
            return 0
        
        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        
        # Add capacity dimension with different capacities per vehicle
        vehicle_capacities = [v['capacity'] for v in data['vehicles']]
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index,
            0,  # null capacity slack
            vehicle_capacities,
            True,  # start cumul to zero
            'Capacity'
        )
        
        # Add pickup and delivery constraints
        # For each request, pickup must come before delivery
        for req_id, (pickup_node, delivery_node) in request_to_nodes.items():
            pickup_index = manager.NodeToIndex(pickup_node)
            delivery_index = manager.NodeToIndex(delivery_node)
            routing.AddPickupAndDelivery(pickup_index, delivery_index)
            # Same vehicle must handle both pickup and delivery
            routing.solver().Add(
                routing.VehicleVar(pickup_index) == routing.VehicleVar(delivery_index)
            )
        
        # Add time dimension
        max_time = 1440  # 24 hours in minutes
        routing.AddDimension(
            time_callback_index,
            30,  # allow waiting time
            max_time,
            False,  # Don't force start cumul to zero
            'Time'
        )
        
        time_dimension = routing.GetDimensionOrDie('Time')
        
        # Set time windows for vehicles (start times)
        for vehicle_id, vehicle in enumerate(data['vehicles']):
            start_index = routing.Start(vehicle_id)
            start_time = vehicle.get('start_time', 0)
            time_dimension.CumulVar(start_index).SetRange(start_time, max_time)
        
        # Set time windows for pickup and delivery nodes
        for req in transfer_requests:
            req_id = req['id']
            pickup_node, delivery_node = request_to_nodes[req_id]
            
            pickup_index = manager.NodeToIndex(pickup_node)
            delivery_index = manager.NodeToIndex(delivery_node)
            
            # Pickup time window
            pickup_tw = req.get('pickup_time_window', [req['arrival_time_at_pickup'], req['arrival_time_at_pickup'] + 120])
            time_dimension.CumulVar(pickup_index).SetRange(pickup_tw[0], pickup_tw[1])
            
            # Delivery time window (if specified)
            if 'delivery_time_window' in req:
                delivery_tw = req['delivery_time_window']
                time_dimension.CumulVar(delivery_index).SetRange(delivery_tw[0], delivery_tw[1])
            else:
                # Default: must be after pickup
                time_dimension.CumulVar(delivery_index).SetRange(pickup_tw[1], max_time)
            
            # Ensure delivery happens after pickup
            time_dimension.CumulVar(pickup_index).SetMax(time_dimension.CumulVar(delivery_index).Max() - 1)
        
        # Set search parameters
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.AUTOMATIC
        )
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.seconds = 60
        
        # Solve
        solution = routing.SolveWithParameters(search_parameters)
        
        if solution:
            return format_pdp_solution(data, manager, routing, solution, request_to_nodes, node_to_request, node_to_location)
        else:
            logger.warning("No solution found for PDP problem")
            return None
            
    except Exception as e:
        logger.error(f"Error solving PDP: {str(e)}", exc_info=True)
        return None


def format_pdp_solution(data, manager, routing, solution, request_to_nodes, node_to_request, node_to_location):
    """Format the PDP solution into JSON-friendly structure"""
    time_dimension = routing.GetDimensionOrDie('Time')
    capacity_dimension = routing.GetDimensionOrDie('Capacity')
    total_distance = 0
    routes = []
    
    for vehicle_id in range(len(data['vehicles'])):
        index = routing.Start(vehicle_id)
        route = {
            'vehicle_id': vehicle_id,
            'stops': [],
            'total_distance': 0,
            'total_time': 0,
            'total_load': 0
        }
        
        route_distance = 0
        
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            time_var = time_dimension.CumulVar(index)
            capacity_var = capacity_dimension.CumulVar(index)
            
            # Get location info
            location_idx = node_to_location.get(node_index, node_index)
            location_info = data['locations'][location_idx] if location_idx < len(data['locations']) else {'name': f'Location {location_idx}'}
            
            # Get request info if this is a pickup/delivery node
            request_info = node_to_request.get(node_index)
            
            stop = {
                'node_index': node_index,
                'location_index': location_idx,
                'location_name': location_info.get('name', f'Location {location_idx}'),
                'arrival_time': solution.Min(time_var),
                'departure_time': solution.Max(time_var),
                'load': solution.Min(capacity_var),
                'is_pickup': request_info and request_info['type'] == 'pickup',
                'is_delivery': request_info and request_info['type'] == 'delivery',
                'request_id': request_info['request_id'] if request_info else None,
                'passengers': abs(request_info['passengers']) if request_info else 0
            }
            
            route['stops'].append(stop)
            
            previous_index = index
            index = solution.Value(routing.NextVar(index))
            route_distance += routing.GetArcCostForVehicle(previous_index, index, vehicle_id)
        
        # Add final stop
        node_index = manager.IndexToNode(index)
        location_idx = node_to_location.get(node_index, node_index)
        time_var = time_dimension.CumulVar(index)
        route['stops'].append({
            'node_index': node_index,
            'location_index': location_idx,
            'location_name': data['locations'][location_idx].get('name', 'End'),
            'arrival_time': solution.Min(time_var),
            'departure_time': solution.Max(time_var),
            'load': 0,
            'is_pickup': False,
            'is_delivery': False,
            'request_id': None,
            'passengers': 0
        })
        
        route['total_distance'] = route_distance
        total_distance += route_distance
        
        routes.append(route)
    
    return {
        'objective_value': solution.ObjectiveValue(),
        'total_distance': total_distance,
        'routes': routes,
        'status': 'optimal' if routing.status() == 1 else 'feasible'
    }

