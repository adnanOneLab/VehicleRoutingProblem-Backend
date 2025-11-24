"""
Convert transfer requests into VRP solver format
Takes pickup/delivery requests and converts them to nodes, demands, and time windows
that the existing VRP solver can handle.
"""

def convert_transfer_requests_to_vrp_format(data):
    """
    Convert transfer requests format to VRP solver format
    
    Input format:
    {
        'locations': [{'id': 0, 'name': 'Hotel A', 'lat': ..., 'lng': ...}, ...],
        'vehicles': [
            {'id': 0, 'capacity': 10, 'start_location': 2, 'start_time': 480},
            ...
        ],
        'transfer_requests': [
            {
                'id': 0,
                'pickup_location': 1,  # Source location index
                'delivery_location': 2,  # Destination location index
                'passengers': 4,
                'arrival_time_at_pickup': 600,
                'pickup_time_window': [600, 720],  # Optional
                'delivery_time_window': [720, 900]  # Optional
            },
            ...
        ],
        'distance_matrix': [[...], ...],  # Optional
        'time_matrix': [[...], ...]  # Optional
    }
    
    Output format (for VRP solver):
    {
        'distance_matrix': [[...], ...],  # Extended matrix with pickup/delivery nodes
        'time_matrix': [[...], ...],  # Optional, extended
        'demands': [0, +4, -4, ...],  # Demands at each node
        'time_windows': [[0, 1440], [600, 720], [720, 900], ...],
        'vehicle_capacities': [10, 8, ...],
        'num_vehicles': 2,
        'depot': 0,  # For VRP, we use a single depot index (will handle multiple starts differently)
        'locations': [...],  # Extended locations list
        'vehicle_starts': [2, 0, ...],  # Start location for each vehicle
        'vehicle_start_times': [480, 0, ...],  # Start time for each vehicle
        'pickup_delivery_pairs': [(1, 2), ...]  # (pickup_node, delivery_node) pairs
    }
    """
    locations = data['locations']
    vehicles = data['vehicles']
    transfer_requests = data['transfer_requests']
    
    num_original_locations = len(locations)
    original_distance_matrix = data.get('distance_matrix', [])
    original_time_matrix = data.get('time_matrix')
    
    # For each transfer request, we create pickup and delivery nodes
    # Pickup nodes: at the pickup location
    # Delivery nodes: at the delivery location
    # We'll add these as additional nodes in the matrix
    
    # Mapping: request_id -> (pickup_node_index, delivery_node_index)
    request_to_nodes = {}
    node_to_location = {}  # Maps node index to original location index
    node_to_request_info = {}  # Maps node index to request information
    
    # First, map original locations (nodes 0 to num_original_locations-1)
    for i in range(num_original_locations):
        node_to_location[i] = i
    
    # Add pickup and delivery nodes for each request
    current_node = num_original_locations
    extended_locations = locations.copy()
    
    for req in transfer_requests:
        pickup_node = current_node
        delivery_node = current_node + 1
        current_node += 2
        
        request_to_nodes[req['id']] = (pickup_node, delivery_node)
        
        # Pickup node is at pickup location
        pickup_loc = locations[req['pickup_location']]
        node_to_location[pickup_node] = req['pickup_location']
        node_to_request_info[pickup_node] = {
            'type': 'pickup',
            'request_id': req['id'],
            'passengers': req['passengers']
        }
        extended_locations.append({
            'id': pickup_node,
            'name': f"Pickup: {pickup_loc['name']} (Request {req['id']})",
            'lat': pickup_loc['lat'],
            'lng': pickup_loc['lng'],
            'original_location': req['pickup_location']
        })
        
        # Delivery node is at delivery location
        delivery_loc = locations[req['delivery_location']]
        node_to_location[delivery_node] = req['delivery_location']
        node_to_request_info[delivery_node] = {
            'type': 'delivery',
            'request_id': req['id'],
            'passengers': -req['passengers']  # Negative for delivery
        }
        extended_locations.append({
            'id': delivery_node,
            'name': f"Delivery: {delivery_loc['name']} (Request {req['id']})",
            'lat': delivery_loc['lat'],
            'lng': delivery_loc['lng'],
            'original_location': req['delivery_location']
        })
    
    total_nodes = current_node
    
    # Build extended distance matrix
    # If nodes are at the same physical location, distance is 0
    extended_distance_matrix = []
    for i in range(total_nodes):
        row = []
        for j in range(total_nodes):
            if i == j:
                row.append(0)
            else:
                loc_i = node_to_location[i]
                loc_j = node_to_location[j]
                if loc_i == loc_j:
                    row.append(0)  # Same physical location
                else:
                    # Use original distance matrix
                    if original_distance_matrix and len(original_distance_matrix) > loc_i and len(original_distance_matrix[loc_i]) > loc_j:
                        row.append(original_distance_matrix[loc_i][loc_j])
                    else:
                        # Calculate Haversine distance if matrix not provided
                        from math import sin, cos, atan2, sqrt, radians
                        loc1 = locations[loc_i]
                        loc2 = locations[loc_j]
                        R = 6371  # Earth's radius in km
                        dlat = radians(loc2['lat'] - loc1['lat'])
                        dlng = radians(loc2['lng'] - loc1['lng'])
                        a = sin(dlat/2)**2 + cos(radians(loc1['lat'])) * cos(radians(loc2['lat'])) * sin(dlng/2)**2
                        c = 2 * atan2(sqrt(a), sqrt(1-a))
                        row.append(round(R * c))
        extended_distance_matrix.append(row)
    
    # Build extended time matrix if provided
    extended_time_matrix = None
    if original_time_matrix:
        extended_time_matrix = []
        for i in range(total_nodes):
            row = []
            for j in range(total_nodes):
                if i == j:
                    row.append(0)
                else:
                    loc_i = node_to_location[i]
                    loc_j = node_to_location[j]
                    if loc_i == loc_j:
                        row.append(0)
                    else:
                        if len(original_time_matrix) > loc_i and len(original_time_matrix[loc_i]) > loc_j:
                            row.append(original_time_matrix[loc_i][loc_j])
                        else:
                            # Convert distance to time
                            distance = extended_distance_matrix[i][j]
                            row.append(int(distance / 0.833))  # 50 km/h = 0.833 km/min
            extended_time_matrix.append(row)
    
    # Build demands array
    demands = [0] * total_nodes
    for node_idx, req_info in node_to_request_info.items():
        demands[node_idx] = req_info['passengers']
    
    # Build time windows array
    time_windows = []
    max_time = 1440  # 24 hours
    
    # Original locations: all day (or can be customized)
    for i in range(num_original_locations):
        time_windows.append([0, max_time])
    
    # Pickup and delivery nodes: use time windows from requests
    for req in transfer_requests:
        req_id = req['id']
        pickup_node, delivery_node = request_to_nodes[req_id]
        
        # Pickup time window
        if 'pickup_time_window' in req:
            pickup_tw = req['pickup_time_window']
        else:
            # Default: arrival time ± 1 hour
            arrival = req['arrival_time_at_pickup']
            pickup_tw = [arrival, arrival + 120]
        time_windows.append(pickup_tw)
        
        # Delivery time window
        if 'delivery_time_window' in req:
            delivery_tw = req['delivery_time_window']
        else:
            # Default: after pickup window ends
            delivery_tw = [pickup_tw[1], max_time]
        time_windows.append(delivery_tw)
    
    # Vehicle capacities
    vehicle_capacities = [v['capacity'] for v in vehicles]
    
    # Vehicle start locations and times
    vehicle_starts = [v['start_location'] for v in vehicles]
    vehicle_start_times = [v.get('start_time', 0) for v in vehicles]
    
    # Pickup-delivery pairs (for constraint enforcement)
    pickup_delivery_pairs = [(pickup, delivery) for pickup, delivery in request_to_nodes.values()]
    
    # For VRP solver, we need a single depot index
    # We'll use the first vehicle's start location as the "depot"
    # But we'll handle multiple starts by modifying the solver
    depot = vehicle_starts[0] if vehicle_starts else 0
    
    return {
        'distance_matrix': extended_distance_matrix,
        'time_matrix': extended_time_matrix,
        'demands': demands,
        'time_windows': time_windows,
        'vehicle_capacities': vehicle_capacities,
        'num_vehicles': len(vehicles),
        'depot': depot,
        'locations': extended_locations,
        'vehicle_starts': vehicle_starts,
        'vehicle_start_times': vehicle_start_times,
        'pickup_delivery_pairs': pickup_delivery_pairs,
        'request_to_nodes': request_to_nodes,
        'node_to_location': node_to_location,
        'node_to_request_info': node_to_request_info
    }

