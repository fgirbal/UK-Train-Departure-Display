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

def renderTfLDepartureRow(departure_info, font):
    """Render a single departure row: [index] [destination] [time]"""
    def drawText(draw, width, height):
        index = departure_info['index']
        destination = departure_info['destination']
        time_display = departure_info['time_display']
        
        # Draw index on the left
        draw.text((0, 0), text=index, font=font, fill="yellow")
        
        # Draw destination in the middle
        draw.text((20, 0), text=destination, font=font, fill="yellow")
        
        # Calculate width for right-aligned time
        time_width, _ = draw.textsize(time_display, font)
        draw.text((width - time_width, 0), text=time_display, font=font, fill="yellow")
    
    return drawText

def renderTfLTime(font):
    """Render centered time in HH:MM:SS format"""
    def drawText(draw, width, height):
        now = datetime.now()
        time_str = now.strftime('%H:%M:%S')
        
        # Calculate width for centered text
        time_width, _ = draw.textsize(time_str, font)
        x_pos = (width - time_width) // 2
        
        draw.text((x_pos, 0), text=time_str, font=font, fill="yellow")
    
    return drawText

def loadTfLData(apiConfig, journeyConfig):
    """Load TfL data with operating hours check"""
    runHours = [int(x) for x in apiConfig['operatingHours'].split('-')]
    if isRun(runHours[0], runHours[1]) == False:
        return False, journeyConfig.get('outOfHoursName', 'Service not operating')

    departures, stationName = loadDeparturesForStationTfL(journeyConfig)

    if len(departures) == 0:
        return False, stationName

    return departures, stationName

def drawTfLBlankSignage(device, width, height, stationName, font):
    """Draw blank signage when no departures available"""
    device.clear()
    virtualViewport = viewport(device, width=width, height=height)

    def renderStationName(draw, canvas_width, canvas_height):
        text = f"No departures from {stationName}"
        text_width, _ = draw.textsize(text, font)
        x_pos = (canvas_width - text_width) // 2
        draw.text((x_pos, 0), text=text, font=font, fill="yellow")

    def renderTime(draw, canvas_width, canvas_height):
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

def drawTfLSignage(device, width, height, departures, stationName, font_regular, font_bold, rotationStart=None):
    """Draw TfL underground-style departure board with 4 lines and rotation"""
    device.clear()
    virtualViewport = viewport(device, width=width, height=height)

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

    # Clear any existing hotspots
    if len(virtualViewport._hotspots) > 0:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

    # Y positions for the 4 departure rows - closer together to fit 4 lines
    y_positions = [4, 16, 28, 40]  
    
    # Show first train, then rotated 2-4 positions
    display_indices = [0]  # Always show first train
    if len(all_formatted) > 1:
        # Add trains 2-4 with rotation offset
        for i in range(1, 4):
            train_index = i + rotation_offset
            if train_index < len(all_formatted):
                display_indices.append(train_index)
    
    # Create departure rows
    for i, train_index in enumerate(display_indices):
        if i < 4 and train_index < len(all_formatted):  # Only show first 4 rows
            departure = all_formatted[train_index].copy()
            departure['index'] = str(i + 1)  # Always number 1-4 for display
            
            departure_row = snapshot(
                width, 12, 
                renderTfLDepartureRow(departure, font_regular), 
                interval=1
            )
            virtualViewport.add_hotspot(departure_row, (0, y_positions[i]))

    # Add time row at the bottom
    time_row = snapshot(width, 12, renderTfLTime(font_bold), interval=1)
    virtualViewport.add_hotspot(time_row, (0, 52))  # Moved up to make room for 4 lines

    return virtualViewport

def main():
    try:
        config = loadConfig()

        device = get_device()
        font_bold = makeFont("Dot Matrix Bold.ttf", 10)  # For time display
        font_regular = makeFont("Dot Matrix Regular.ttf", 10)  # For departures

        widgetWidth = 256
        widgetHeight = 64

        # Load initial TfL data
        data = loadTfLData(config["tflApi"], config["tflJourney"])
        
        if data[0] == False:
            # No departures available
            station_name = getTfLStationDisplayName(data[1])
            virtual = drawTfLBlankSignage(device, widgetWidth, widgetHeight, station_name, font_regular)
        else:
            # Display departures
            departures, raw_station_name = data
            station_name = getTfLStationDisplayName(raw_station_name)
            virtual = drawTfLSignage(device, widgetWidth, widgetHeight, departures, station_name, font_regular, font_bold)

        timeAtStart = time.time()
        timeNow = time.time()
        rotationStart = time.time()  # Track rotation timing

        print(f"TfL Departure Display started for {station_name}")
        print("Press Ctrl+C to stop")

        while True:
            # Refresh data every refreshTime seconds
            if(timeNow - timeAtStart >= config["refreshTime"]):
                print("Refreshing TfL data...")
                
                data = loadTfLData(config["tflApi"], config["tflJourney"])
                
                if data[0] == False:
                    station_name = getTfLStationDisplayName(data[1])
                    virtual = drawTfLBlankSignage(device, widgetWidth, widgetHeight, station_name, font_regular)
                else:
                    departures, raw_station_name = data
                    station_name = getTfLStationDisplayName(raw_station_name)
                    
                    # Reset rotation when data refreshes
                    rotationStart = time.time()
                    virtual = drawTfLSignage(device, widgetWidth, widgetHeight, departures, station_name, font_regular, font_bold, rotationStart)
                    
                    # Print current departures to console
                    formatted = formatTfLDeparturesForDisplay(departures)
                    print(f"Next departures from {station_name}:")
                    for dep in formatted[:4]:  # Show 4 departures
                        print(f"  {dep['index']}. {dep['destination']} - {dep['time_display']}")

                timeAtStart = time.time()
            
            # Update display with rotation every 5 seconds (but don't refresh data)
            elif data[0] != False and (timeNow - rotationStart >= 5):
                departures, raw_station_name = data
                station_name = getTfLStationDisplayName(raw_station_name)
                virtual = drawTfLSignage(device, widgetWidth, widgetHeight, departures, station_name, font_regular, font_bold, rotationStart)

            timeNow = time.time()
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
