# *****************************************************************************
# * Copyright by ams-OSRAM AG                                                 *
# * All rights are reserved.                                                  *
# *                                                                           *
# *FOR FULL LICENSE TEXT SEE LICENSES-MIT.TXT                                 *
# *****************************************************************************

import __init__
import numpy as np
import tmf8829_zeromq_client_class as zeromq_client  # to get the measurement results
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import math
import os
import time

# start from https://medium.com/@akanshsaxena123/opencv-hand-recognition-a-guide-to-real-time-gesture-detection-8a53ec345033
# update to Python 3.13 and added pinch detection.

# need Python 3.13
# downloaded hand_landmarker.task from 
# https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
# MediaPipe Hand Landmarker Model
# Copyright Google LLC
# Licensed under the Apache License, Version 2.0
# https://www.apache.org/licenses/LICENSE-2.0 and tmf8829/zeromq/LICENSE-Apache-2.0.txt

# Configuration for the new Tasks API
#   Get the directory where THIS script is currently saved
script_dir = os.path.dirname(os.path.abspath(__file__))
#   Join it with the filename to get the absolute path
model_path = os.path.join(script_dir, 'hand_landmarker.task')
base_options = python.BaseOptions(model_asset_path=model_path)
options = vision.HandLandmarkerOptions(base_options=base_options, num_hands=2, running_mode=vision.RunningMode.VIDEO)
detector = vision.HandLandmarker.create_from_options(options)

# Dictionary mapping fingertip landmark indices to their descriptive numbers/labels
FINGERTIP_MAP = {
    4: "Thumb",   # Thumb Tip
    8: "Index",   # Index Tip
    12: "Middle", # Middle Tip
    16: "Ring",   # Ring Tip
    20: "Pinky"   # Pinky Tip
}

def hand_pinch_detection(frame, enable_landmark=True):
    # 1. Convert to MediaPipe Image format
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)

    # 2. Detect
    timestamp_ms = int(time.time() * 1000)
    detection_result = detector.detect_for_video(mp_image, timestamp_ms)
    
    # 3. Draw Landmarks manually
    if detection_result.hand_landmarks:
        for hand_landmarks_list in detection_result.hand_landmarks:
            # Convert MediaPipe NormalizedLandmark to a list for OpenCV
            h, w, _ = frame.shape
            # Using enumerate to track the landmark index (0 to 20)
            for idx, landmark in enumerate(hand_landmarks_list):
                cx, cy = int(landmark.x * w), int(landmark.y * h)
                
                # Draw the landmark point
                cv2.circle(frame, (cx, cy), 5, (0, 255, 0), -1)
                
                # If this landmark is a fingertip, draw its name next to it
                if idx in FINGERTIP_MAP:
                    label = FINGERTIP_MAP[idx]
                    # Offset the text slightly (10px right, 10px up) so it doesn't overlap the circle
                    cv2.putText(
                        frame, 
                        label, 
                        (cx + 10, cy - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 
                        0.6,          # Font scale (size)
                        (0, 255, 255),  # Yellow color in BGR
                        2,            # Thickness
                        cv2.LINE_AA   # Anti-aliased line for smoother text
                    )

            # Get coordinates for Thumb Tip (4) and Index Tip (8)
            thumb_tip = hand_landmarks_list[4]
            index_tip = hand_landmarks_list[8]
            
            # Convert normalized coordinates to pixel values
            h, w, _ = frame.shape
            x1, y1 = int(thumb_tip.x * w), int(thumb_tip.y * h)
            x2, y2 = int(index_tip.x * w), int(index_tip.y * h)
            
            # Calculate Euclidean distance
            distance = math.hypot(x2 - x1, y2 - y1)
            
            # Threshold: if distance < 100 pixels, start drawing connection line
            if distance < 100:
                # Draw the connection line
                cv2.line(frame, (x1, y1), (x2, y2), (255, 0, 0), 3)   

            # Threshold: if distance < 50 pixels, it's a "pinch"
            if distance < 50:
                cv2.putText(frame, "PINCH DETECTED", (50, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)        
                # Add your action here (e.g., click a button, trigger an event)
    return frame

if __name__ == "__main__":
    
    # connect to EVM
    tmf8829_evm = zeromq_client.tmf8829_evm_connector()

    ZMIN = 50
    ZMAX = 550  # limit data to this range

    enable_landmark = True

    # Loop
    try:

        while True:
            pixelResults, *_ = tmf8829_evm.measure()
            rows = len(pixelResults)
            cols = len(pixelResults[0])
            # extract z position (flat target corrected depth) of every pixel
            z_array = np.array([pixel['peaks'][0]['z'] for row in pixelResults for pixel in row]).reshape(rows, cols)
            signal_array = np.array([pixel['peaks'][0]['signal'] for row in pixelResults for pixel in row]).reshape(rows, cols)

            # disable pixels which are outside of range
            mask = (z_array < ZMIN) | (z_array > ZMAX)
            signal_array[mask] = 0
            z_array[mask] = 0

            # de-noise - this filter is for smoother visualization, it does not really affect detection performance
            # cv2.bilateralFilter(src, d, sigmaColor, sigmaSpace)
            # d: Diameter of each pixel neighborhood (keep it small, e.g., 3 or 5)
            # sigmaColor: Higher values mean farther values will mix together; need to change with range of data
            # sigmaSpace: Higher values mean farther pixels will influence each other
            signal_array = cv2.bilateralFilter(signal_array.astype(np.float32), d=5, sigmaColor=100, sigmaSpace=15)

            # Dynamically stretch the min/max values to span the full 0-255 range
            visual_array = cv2.normalize(signal_array, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
           
            # scale to larger smooth image
            smooth_large_image = cv2.resize(visual_array, (800, 600), interpolation=cv2.INTER_CUBIC).astype(np.uint8)
            # alternative method but similar output and detection performance
            # smooth_large_image = cv2.resize(visual_array, (800, 600), interpolation=cv2.INTER_LANCZOS4).astype(np.uint8)
            # no interpolation, uncomment next line, degrades detection performance
            # smooth_large_image = cv2.resize(visual_array, (800, 600), interpolation=cv2.INTER_NEAREST).astype(np.uint8)

            # convert to RGB image
            frame = cv2.cvtColor(smooth_large_image, cv2.COLOR_GRAY2RGB)

            # perform landmark and pinch detection
            if enable_landmark:
                frame = hand_pinch_detection(frame)
            else:
                cv2.putText(frame, "Hand detection disabled", (50, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            # add average distance
            z_valid_results = z_array[z_array>0]
            if z_valid_results.any():
                average_distance = z_valid_results.mean().astype(int)
                cv2.putText(frame, f"Average distance {average_distance} mm", (50, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            else:
                cv2.putText(frame, f"No object from {ZMIN} mm to {ZMAX} mm", (50, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            cv2.imshow('Image from TMF8829', frame)
            if cv2.waitKey(1) >= 0:  # toggle this on any key
                enable_landmark = not enable_landmark

    except KeyboardInterrupt:
        print("\nScript closed.")

    # close EVM
    tmf8829_evm.end_connection()

    cv2.destroyAllWindows()

