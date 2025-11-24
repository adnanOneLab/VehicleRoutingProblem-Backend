# Pickup and Delivery Problem (PDP) Implementation

## Overview

This implementation supports a **Pickup and Delivery Problem (PDP)** with the following features:

1. **Multiple Depots**: Any location can be a starting point for vehicles
2. **Transfer Requests**: Define passenger transfers from source to destination
3. **Different Vehicle Capacities**: Each vehicle can have its own capacity
4. **Dynamic Capacity**: Vehicles pick up and drop off passengers along routes

## Data Model

### Transfer Request
```json
{
  "id": 0,
  "pickup_location": 1,           // Source location index
  "delivery_location": 2,          // Destination location index
  "passengers": 4,                 // Number of people
  "arrival_time_at_pickup": 600,   // When passengers arrive at pickup (minutes from midnight)
  "pickup_time_window": [600, 720], // Time window for pickup [start, end]
  "delivery_time_window": [720, 900] // Optional: Time window for delivery
}
```

### Vehicle Configuration
```json
{
  "id": 0,
  "capacity": 10,                  // Max passengers
  "start_location": 2,             // Can start at any location (hotel, airport, etc.)
  "start_time": 480                // Optional: When vehicle becomes available (default: 0)
}
```

## How It Works

1. **Pickup and Delivery Nodes**: Each transfer request creates 2 nodes:
   - Pickup node at source location
   - Delivery node at destination location

2. **Constraints**:
   - Pickup must happen before delivery (same vehicle)
   - Vehicle capacity cannot be exceeded
   - Time windows must be respected
   - Vehicles start at their designated locations

3. **Example Scenario**:
   - Vehicle 1 starts at Hotel A (capacity: 10)
   - Vehicle 2 starts at Airport (capacity: 8)
   - Request 1: Pickup 4 people from Hotel A → Drop at Hotel B (arrival at Hotel A: 8:00 AM)
   - Request 2: Pickup 3 people from Hotel B → Drop at Airport (arrival at Hotel B: 10:00 AM)

## API Endpoint

**POST** `/vehicle_routing/solve-pdp`

**Request Body**:
```json
{
  "locations": [
    {"id": 0, "name": "Hotel A", "lat": 18.5204, "lng": 73.8567},
    {"id": 1, "name": "Hotel B", "lat": 18.5642, "lng": 73.7769},
    {"id": 2, "name": "Airport", "lat": 18.5822, "lng": 73.9197}
  ],
  "vehicles": [
    {"id": 0, "capacity": 10, "start_location": 0, "start_time": 480},
    {"id": 1, "capacity": 8, "start_location": 2, "start_time": 0}
  ],
  "transfer_requests": [
    {
      "id": 0,
      "pickup_location": 0,
      "delivery_location": 1,
      "passengers": 4,
      "arrival_time_at_pickup": 600,
      "pickup_time_window": [600, 720]
    }
  ],
  "distance_matrix": [[...], ...],  // Optional, will be calculated if not provided
  "time_matrix": [[...], ...]        // Optional
}
```

## Next Steps for Frontend

1. Add UI for creating transfer requests
2. Add vehicle configuration with start locations
3. Update visualization to show pickup/delivery nodes
4. Add mode toggle (VRP vs PDP)

