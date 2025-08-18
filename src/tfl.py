import requests
import json
from datetime import datetime, timedelta

def abbrStation(journeyConfig, inputStr):
    """Apply station abbreviations from config"""
    dict = journeyConfig.get('stationAbbr', {})
    for key in dict.keys():
        inputStr = inputStr.replace(key, dict[key])
    return inputStr

def loadDeparturesForStationTfL(journeyConfig):
    """Load departures for a TfL station using the TfL API"""
    if journeyConfig["departureStation"] == "":
        raise ValueError(
            "Please set the journey.departureStation property in config.json")

    departureStation = journeyConfig["departureStation"]
    
    # TfL API endpoint for arrivals at a station
    url = f"https://api.tfl.gov.uk/StopPoint/{departureStation}/Arrivals"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        raise ValueError(f"Failed to fetch TfL data: {e}")
    
    if not data:
        return [], departureStation
    
    # Sort by expected arrival time
    data.sort(key=lambda x: x['expectedArrival'])
    
    # Apply filters if specified
    filtered_data = data
    
    # Filter by line if specified
    if journeyConfig.get("filterByLine"):
        line_filter = journeyConfig["filterByLine"].lower()
        filtered_data = [item for item in filtered_data 
                        if item.get('lineName', '').lower() == line_filter]
    
    # Filter by direction if specified  
    if journeyConfig.get("filterByDirection"):
        direction_filter = journeyConfig["filterByDirection"].lower()
        filtered_data = [item for item in filtered_data 
                        if (direction_filter in item.get('direction', '').lower() or
                            direction_filter in item.get('platformName', '').lower())]
    
    translated_departures = []
    
    # Take first 5 departures from filtered results
    for item in filtered_data[:5]:
        # Convert expected arrival to departure time format
        expected_arrival = datetime.fromisoformat(item['expectedArrival'].replace('Z', '+00:00'))
        aimed_departure_time = expected_arrival.strftime('%H:%M')
        expected_departure_time = aimed_departure_time  # For TfL, these are the same
        
        # Extract destination name and apply abbreviations
        destination_name = item['destinationName'].replace(' Underground Station', '')
        destination_name = abbrStation(journeyConfig, destination_name)
        
        # Extract platform from platformName (e.g., "Northbound - Platform 1" -> "1")
        platform_name = item.get('platformName', '')
        platform = ""
        if 'Platform' in platform_name:
            platform = platform_name.split('Platform')[-1].strip()
        
        # Calculate time to station in minutes
        time_to_station_seconds = item.get('timeToStation', 0)
        time_to_station_minutes = time_to_station_seconds // 60
        
        # Status based on time to station
        if time_to_station_minutes <= 1:
            status = "Due"
        else:
            status = f"{time_to_station_minutes} min"
        
        translated_departures.append({
            'uid': item['id'],
            'destination_name': destination_name,
            'aimed_departure_time': aimed_departure_time,
            'expected_departure_time': expected_departure_time,
            'status': status,
            'mode': item.get('modeName', 'tube'),
            'platform': platform,
            'line_name': item.get('lineName', ''),
            'towards': item.get('towards', ''),
            'current_location': item.get('currentLocation', ''),
            'timeToStation': time_to_station_seconds  # Add this for the new display
        })
    
    # Extract station name
    station_name = data[0]['stationName'].replace(' Underground Station', '') if data else departureStation
    
    return translated_departures, station_name

def loadDestinationsForDepartureTfL(journeyConfig, departure_info):
    """
    Load destinations for a TfL departure
    For TfL, we'll return the line name and direction as the 'calling at' information
    since TfL doesn't provide intermediate stops in the arrivals API
    """
    if not departure_info:
        return []
    
    # For TfL, we'll show the line and direction instead of intermediate stops
    calling_at = []
    
    # Add line information
    line_name = departure_info.get('line_name', '')
    towards = departure_info.get('towards', '')
    current_location = departure_info.get('current_location', '')
    
    if line_name:
        calling_at.append(f"{line_name} line")
    
    if towards:
        calling_at.append(f"towards {towards}")
    
    if current_location and current_location != "At Platform":
        calling_at.append(f"currently {current_location}")
    
    # If we only have one item, add "only" to match the trains.py pattern
    if len(calling_at) == 1:
        calling_at[0] = calling_at[0] + ' only.'
    
    return calling_at

def formatTfLDeparturesForDisplay(departures):
    """
    Format TfL departures for the underground-style display
    Returns a list of formatted departure entries
    """
    formatted_departures = []
    
    for i, departure in enumerate(departures[:3], 1):  # Only take first 3
        # Calculate time to station in minutes
        time_to_station_seconds = departure.get('timeToStation', 0) if 'timeToStation' in departure else 0
        time_to_station_minutes = time_to_station_seconds // 60
        
        # Format the time display
        if time_to_station_minutes <= 1:
            time_display = "Due"
        else:
            time_display = f"{time_to_station_minutes} mins"
        
        # Clean up destination name
        destination = departure['destination_name']
        
        formatted_departures.append({
            'index': str(i),
            'destination': destination,
            'time_display': time_display,
            'line_name': departure.get('line_name', ''),
            'platform': departure.get('platform', '')
        })
    
    return formatted_departures

def getTfLStationDisplayName(station_name):
    """
    Format station name for display (remove 'Underground Station' suffix)
    """
    return station_name.replace(' Underground Station', '').replace(' Station', '')
