# *****************************************************************************
# * Copyright by ams OSRAM AG                                                 *
# * All rights are reserved.                                                  *
# *                                                                           *
# *FOR FULL LICENSE TEXT SEE LICENSES-MIT.TXT                                 *
# *****************************************************************************

# Example 3d point cloud visualization 

import numpy as np
import matplotlib.pyplot as plt
import tmf8829_zeromq_client_class as zeromq_client  # to get the measurement results


if __name__ == "__main__":
    # connect to EVM
    tmf8829_evm = zeromq_client.tmf8829_evm_connector()

    # 1. Turn on interactive mode
    plt.ion()

    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    # Initial dummy data
    points = np.random.uniform(-1, 1, (100, 3))

    # 2. Create the initial scatter plot object
    # We keep a reference to 'scat' so we can update it later
    scat = ax.scatter(points[:, 0], points[:, 1], points[:, 2], c='b', marker='o')

    # Set fixed axis limits so the box doesn't jump around
    ZMAX = 1000
    XY_MAX = 500

    ax.set_xlim(-XY_MAX, XY_MAX)
    ax.set_ylim(-XY_MAX, XY_MAX)
    ax.set_zlim(0, ZMAX)

    # BEFORE THE LOOP: Cache the background
    fig.canvas.draw()
    background = fig.canvas.copy_from_bbox(fig.bbox)

    # 3. Loop
    try:
        i = 0
        while True:
            pixelResults, *_ = tmf8829_evm.measure()
            rows = len(pixelResults)
            cols = len(pixelResults[0])
            # extract x,y,z position (flat target corrected depth) of every pixel
            pixels = [pixel['peaks'][0] for row in pixelResults for pixel in row]
            x_filtered = []
            y_filtered = []
            z_filtered = []

            for d in pixels:
                if 0 < d['z'] < ZMAX:
                    x_filtered.append(d['x'])
                    y_filtered.append(d['y'])
                    z_filtered.append(d['z'])

            # INSIDE THE LOOP:
            # Restore the clean background
            fig.canvas.restore_region(background)

            # Update the data inside the scatter object
            scat._offsets3d = (x_filtered, y_filtered, z_filtered)
            
            # 4. Redraw ONLY the scatter artist
            ax.draw_artist(scat)
            # Push the pixels to the screen
            fig.canvas.blit(fig.bbox)
            fig.canvas.flush_events()

            # 4. Redraw the figure -- this is too slow...
            # fig.canvas.draw()
            # fig.canvas.flush_events()
    except KeyboardInterrupt:
        print("\nScript closed.")

    # close EVM
    tmf8829_evm.end_connection()

    # Turn off interactive mode when done so the window stays open at the end
    # plt.ioff()
    # plt.show()

