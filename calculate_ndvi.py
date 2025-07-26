import rasterio
import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.mask import mask
import os
import fiona

def read_polygons(polygon_file, selected_layer=None):
    """
    Reads polygons from a shapefile or File Geodatabase (GDB).
    If GDB: uses selected_layer if provided, else defaults to the first.
    """
    if polygon_file.endswith(".gdb"):
        layers = fiona.listlayers(polygon_file)
        if selected_layer and selected_layer in layers:
            return gpd.read_file(polygon_file, layer=selected_layer)
        else:
            return gpd.read_file(polygon_file, layer=layers[0])
    else:
        return gpd.read_file(polygon_file)


def calculate_stats(ndvi_files, polygon_file, plot_id_field, output_dir,
                    progress_callback=None, selected_layer=None):
    """
    Calculates NDVI zonal statistics and NDVI>0.7 area for each plot.
    Supports shapefiles and File Geodatabases, and uses selected GDB layer if provided.
    """
    gdf = read_polygons(polygon_file, selected_layer=selected_layer)

    all_data = {}
    time_labels = [f"Time{i+1}" for i in range(len(ndvi_files))]

    for idx, raster_path in enumerate(ndvi_files):
        label = time_labels[idx]

        # Update progress
        if progress_callback:
            progress_callback(int((idx / len(ndvi_files)) * 100))

        with rasterio.open(raster_path) as src:
            for _, row in gdf.iterrows():
                pid = row[plot_id_field]
                geom = [row.geometry.__geo_interface__]

                # Clip raster by polygon
                out_image, _ = mask(src, geom, crop=True)
                ndvi_data = out_image[0]

                # Remove nodata
                ndvi_data = ndvi_data[ndvi_data != src.nodata]
                if ndvi_data.size == 0:
                    continue

                # Calculate statistics
                stats = {
                    f"{label}_MEAN": float(np.mean(ndvi_data)),
                    f"{label}_MEDIAN": float(np.median(ndvi_data)),
                    f"{label}_STD": float(np.std(ndvi_data)),
                    f"{label}_RANGE": float(np.max(ndvi_data) - np.min(ndvi_data)),
                    f"{label}_SUM": float(np.sum(ndvi_data)),
                    f"{label}_NDVI>0.7_area": float(np.count_nonzero(ndvi_data > 0.7))
                }

                if pid not in all_data:
                    all_data[pid] = {}
                all_data[pid].update(stats)

    # Final progress = 100%
    if progress_callback:
        progress_callback(100)

    # Save results
    df = pd.DataFrame.from_dict(all_data, orient="index")
    df.insert(0, "PlotID", df.index)
    df.reset_index(drop=True, inplace=True)

    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "NDVI_TimeSeries_Statistics.xlsx")
    df.to_excel(output_file, index=False)

    return output_file
