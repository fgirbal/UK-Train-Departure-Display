import os
import sys
import time
import json
from datetime import datetime
from PIL import ImageFont, Image
from helpers import get_device
from tfl import loadDeparturesForStationTfL, formatTfLDeparturesForDisplay, getTfLStationDisplayName
from luma.core.render import canvas
from luma.core.virtual import viewport, snapshot
from open import isRun

# Global variables for smooth rotation tracking
g_last_rotation_time = 0
g_rotation_start_index = 1  # Index for row 2 (0-based, so 1 = second train)
g_display_trains_cache = []

# Global font dictionary
g_fonts = {}

def loadConfig():
    with open('config.json', 'r') as jsonConfig:
        data = json.load(jsonConfig)
        return data

def makeFont(name, size):
    font_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            'fonts',
            name
        )
    )
    return ImageFont.truetype(font_path, size)

def initializeFonts():
    """Initialize the global font dictionary"""
    global g_fonts
    g_fonts = {
        'big_bold': makeFont("Dot Matrix Bold.ttf", 17),
        'small_regular': makeFont("Dot Matrix Regular.ttf", 10),
        'small_bold': makeFont("Dot Matrix Bold.ttf", 10)
    }

def renderTfLDepartureRow(departure_info, font):
    """Render a single departure row: [index] [platform] [destination] [time]"""
    def drawText(draw, width, height):
        index = departure_info['index']
        destination = departure_info['destination']
        time_display = departure_info['time_display']
        platform_display = departure_info.get('platform_display', '')
        
        # Draw index on the left
        draw.text((0, 0), text=index, font=font, fill="yellow")
        
        # Draw platform after index
        x_pos = 10
        # if platform_display:
        #     draw.text((x_pos, 0), text=platform_display, font=font, fill="yellow")
        #     platform_width, _ = draw.textsize(platform_display, font)
        #     x_pos += platform_width + 10  # Add some spacing
        
        # Draw destination after platform
        draw.text((x_pos, 0), text=destination + f" ({platform_display})", font=font, fill="yellow")
        
        # Calculate width for right-aligned time
        time_width, _ = draw.textsize(time_display, font)
        draw.text((width - time_width, 0), text=time_display, font=font, fill="yellow")
    
    return drawText

def renderTfLTime():
    """Render centered time in HH:MM:SS format"""
    def drawText(draw, width, height):
        font = g_fonts['big_bold']
        now = datetime.now()
        time_str = now.strftime('%H:%M:%S')
        
        # Calculate width for centered text
        time_width, _ = draw.textsize(time_str, font)
        x_pos = (width - time_width) // 2
        
        draw.text((x_pos, 0), text=time_str, font=font, fill="yellow")
    
    return drawText

def loadTfLData(apiConfig, journeyConfig):
    """Load TfL data with operating hours check"""
    # runHours = [int(x) for x in apiConfig['operatingHours'].split('-')]
    # if isRun(runHours[0], runHours[1]) == False:
    #     return False, journeyConfig.get('outOfHoursName', 'Service not operating')

    departures, stationName = loadDeparturesForStationTfL(journeyConfig)

    if len(departures) == 0:
        return False, stationName

    return departures, stationName

def drawTfLBlankSignage(device, width, height, stationName):
    """Draw blank signage when no departures available"""
    device.clear()
    virtualViewport = viewport(device, width=width, height=height)

    def renderStationName(draw, canvas_width, canvas_height):
        font = g_fonts['small_regular']
        text = f"No departures from {stationName}"
        text_width, _ = draw.textsize(text, font)
        x_pos = (canvas_width - text_width) // 2
        draw.text((x_pos, 0), text=text, font=font, fill="yellow")

    def renderTime(draw, canvas_width, canvas_height):
        font = g_fonts['small_regular']
        now = datetime.now()
        time_str = now.strftime('%H:%M:%S')
        time_width, _ = draw.textsize(time_str, font)
        x_pos = (canvas_width - time_width) // 2
        draw.text((x_pos, 0), text=time_str, font=font, fill="yellow")

    # Clear any existing hotspots
    if len(virtualViewport._hotspots) > 0:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

    # Add message and time
    message_row = snapshot(width, 12, renderStationName, interval=10)
    time_row = snapshot(width, 12, renderTime, interval=1)

    virtualViewport.add_hotspot(message_row, (0, 20))
    virtualViewport.add_hotspot(time_row, (0, 50))

    return virtualViewport

def calculateDisplayTrains(departures, rotationStart=None):
    """Calculate which 4 trains to display with rotation logic"""
    # Format all departures for display (get more than we need for rotation)
    all_formatted = formatTfLDeparturesForDisplay(departures, max_departures=10)
    
    # Calculate rotation offset based on time
    rotation_offset = 0
    if rotationStart and len(all_formatted) > 4:
        elapsed_time = time.time() - rotationStart
        rotation_cycle = int(elapsed_time // 5)  # Change every 5 seconds
        max_offset = len(all_formatted) - 3  # Maximum offset to show last train in position 4
        rotation_offset = min(rotation_cycle, max_offset)
        
        # Reset to beginning when we've shown all
        if rotation_offset >= max_offset:
            rotation_offset = rotation_cycle % (max_offset + 1)

    # Show first train, then rotated 2-4 positions
    display_indices = [0]  # Always show first train
    if len(all_formatted) > 1:
        # Add trains 2-4 with rotation offset
        for i in range(1, 4):
            train_index = i + rotation_offset
            if train_index < len(all_formatted):
                display_indices.append(train_index)
    
    # Build the display trains with correct indices
    display_trains = []
    for train_index in display_indices:
        if train_index < len(all_formatted):
            departure = all_formatted[train_index].copy()
            departure['index'] = str(train_index + 1)  # Show actual train number (1-based)
            display_trains.append(departure)
    
    return display_trains, display_indices

def renderTfLDepartureRotationRow(row_number):
    """Render function for a specific rotating row (2, 3, or 4)"""
    def drawText(draw, width, height):
        global g_last_rotation_time, g_rotation_start_index, g_display_trains_cache
        
        current_time = time.time()
        
        # Check if it's time to rotate (every 5 seconds) - only update on first row check
        if row_number == 2 and current_time - g_last_rotation_time >= 5.0:
            # Advance the rotation
            g_rotation_start_index += 1
            
            # Make sure we don't exceed available trains (keep at least 4 trains visible)
            max_start_index = max(1, len(g_display_trains_cache) - 3)
            if g_rotation_start_index > max_start_index:
                g_rotation_start_index = 1  # Reset to beginning
            
            g_last_rotation_time = current_time
            print(f"Rotating display (start index: {g_rotation_start_index})")
        
        # Calculate which train to show for this row
        train_index = g_rotation_start_index + (row_number - 2)  # row 2 = index 0, row 3 = index 1, etc.
        
        if train_index < len(g_display_trains_cache):
            train = g_display_trains_cache[train_index].copy()
            train['index'] = str(train_index + 1)  # Show actual train number (1-based)
            
            # Render this train row using the existing function
            renderTfLDepartureRow(train, g_fonts['small_regular'])(draw, width, height)

    return drawText

def getCurrentDisplayTrains():
    """Get current display trains for console output"""
    global g_rotation_start_index, g_display_trains_cache
    
    current_display_trains = []
    
    # Always show first train in row 1
    if len(g_display_trains_cache) > 0:
        first_train = g_display_trains_cache[0].copy()
        first_train['index'] = '1'
        current_display_trains.append(first_train)
    
    # Add rotated trains for rows 2-4
    for i in range(3):  # Rows 2, 3, 4
        train_index = g_rotation_start_index + i
        if train_index < len(g_display_trains_cache):
            train = g_display_trains_cache[train_index].copy()
            train['index'] = str(train_index + 1)  # Show actual train number (1-based)
            current_display_trains.append(train)
    
    return current_display_trains

def precomputeDisplayTrains(departures):
    """Pre-compute and cache all formatted train data"""
    global g_display_trains_cache, g_rotation_start_index, g_last_rotation_time
    
    # Format all departures for display
    g_display_trains_cache = formatTfLDeparturesForDisplay(departures, max_departures=10)
    
    # Reset rotation state when new data comes in
    g_rotation_start_index = 1
    g_last_rotation_time = time.time()

def drawTfLSignage(device, width, height, display_trains, stationName, n_rows = 4):
    """Draw TfL underground-style departure board with n_rows lines"""
    device.clear()
    virtualViewport = viewport(device, width=width, height=height)

    # Clear any existing hotspots
    if len(virtualViewport._hotspots) > 0:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

    line_spacing = 12
    
    # Row 1: Fixed first train
    if len(g_display_trains_cache) > 0:
        first_train = g_display_trains_cache[0].copy()
        first_train['index'] = '1'
        first_train_row = snapshot(
            width, 12,
            renderTfLDepartureRow(first_train, g_fonts['small_bold']),
            interval=1
        )
        virtualViewport.add_hotspot(first_train_row, (0, 0))
    
    # Rows 2-4: Rotating trains using individual snapshots
    for row_num in range(2, min(n_rows + 1, 5)):  # rows 2, 3, 4
        y_pos = (row_num - 1) * line_spacing
        rotation_row = snapshot(
            width, 12,
            renderTfLDepartureRotationRow(row_num),
            interval=1
        )
        virtualViewport.add_hotspot(rotation_row, (0, y_pos))

    # Add time row at the bottom
    time_row = snapshot(width, 12, renderTfLTime(), interval=1)
    virtualViewport.add_hotspot(time_row, (0, height - 14))

    return virtualViewport

def main():
    try:
        config = loadConfig()

        # Initialize fonts
        initializeFonts()

        device = get_device()
        widgetWidth = 256
        widgetHeight = 64

        # Load initial TfL data
        data = loadTfLData(config["tflApi"], config["tflJourney"])
        
        if data[0] == False:
            # No departures available
            station_name = getTfLStationDisplayName(data[1])
            virtual = drawTfLBlankSignage(device, widgetWidth, widgetHeight, station_name)
        else:
            # Display departures
            departures, raw_station_name = data
            station_name = getTfLStationDisplayName(raw_station_name)
            precomputeDisplayTrains(departures)
            virtual = drawTfLSignage(device, widgetWidth, widgetHeight, [], station_name)

        timeAtStart = time.time()
        
        print(f"TfL Departure Display started for {station_name}")
        print("Press Ctrl+C to stop")

        while True:
            timeNow = time.time()
            
            # Refresh data every refreshTime seconds
            if(timeNow - timeAtStart >= config["refreshTime"]):
                print("Refreshing TfL data...")
                
                data = loadTfLData(config["tflApi"], config["tflJourney"])
                
                if data[0] == False:
                    station_name = getTfLStationDisplayName(data[1])
                    virtual = drawTfLBlankSignage(device, widgetWidth, widgetHeight, station_name)
                else:
                    departures, raw_station_name = data
                    station_name = getTfLStationDisplayName(raw_station_name)
                    
                    # Reset rotation and precompute new display data
                    precomputeDisplayTrains(departures)
                    virtual = drawTfLSignage(device, widgetWidth, widgetHeight, [], station_name)
                    
                    # Print current departures to console
                    current_trains = getCurrentDisplayTrains()
                    print(f"Next departures from {station_name}:")
                    for train_info in current_trains:
                        print(f"  {train_info['index']}. {train_info['destination']} - {train_info['time_display']}")

                timeAtStart = time.time()

            virtual.refresh()

    except KeyboardInterrupt:
        print("\nTfL Display stopped")
        pass
    except ValueError as err:
        print(f"Error: {err}")
    except KeyError as err:
        print(f"Error: Please ensure the {err} environment variable is set")
    except Exception as err:
        print(f"Unexpected error: {err}")

if __name__ == "__main__":
    main()
