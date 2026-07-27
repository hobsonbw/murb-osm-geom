import numpy as np
import pandas as pd

from shapely import wkt
from scipy import ndimage

from skimage.draw import polygon as raster_polygon
from skimage.morphology import medial_axis

INPUT_CSV = "data/outputs/kingston_smoke_subset.csv"

GEOMETRY_COLUMN = "geometry_wkt"

RASTER_RESOLUTION = 0.5
MIN_BRANCH_LENGTH = 10.0


def polygon_to_raster(poly, resolution=0.5, padding=5):

    minx, miny, maxx, maxy = poly.bounds

    width = int(np.ceil((maxx - minx) / resolution)) + 2 * padding
    height = int(np.ceil((maxy - miny) / resolution)) + 2 * padding

    raster = np.zeros((height, width), dtype=bool)

    coords = np.array(poly.exterior.coords)

    x = (coords[:, 0] - minx) / resolution + padding
    y = (coords[:, 1] - miny) / resolution + padding

    rr, cc = raster_polygon(y, x, raster.shape)

    raster[rr, cc] = True

    return raster


def get_branches(binary):

    skeleton, distance = medial_axis(
        binary,
        return_distance=True
    )

    kernel = np.ones((3, 3), dtype=int)

    neighbour_count = (
        ndimage.convolve(
            skeleton.astype(int),
            kernel,
            mode="constant",
        )
        - skeleton.astype(int)
    )

    branch_nodes = skeleton & (neighbour_count > 2)

    segments = skeleton & (~branch_nodes)

    labels, n_labels = ndimage.label(segments)

    return labels, n_labels, distance


def calculate_average_depth(
    polygon_wkt,
    resolution=RASTER_RESOLUTION,
    min_branch_length=MIN_BRANCH_LENGTH,
):

    try:
        poly = wkt.loads(polygon_wkt)
    except Exception:
        return np.nan

    raster = polygon_to_raster(
        poly,
        resolution=resolution,
    )

    labels, n_labels, distance = get_branches(raster)

    branch_lengths = []
    branch_depths = []

    for label_id in range(1, n_labels + 1):

        mask = labels == label_id

        branch_length = mask.sum() * resolution

        # remove tiny skeleton spurs
        if branch_length < min_branch_length:
            continue

        depths = (
            2.0
            * distance[mask]
            * resolution
        )

        branch_lengths.append(branch_length)
        branch_depths.append(depths.mean())

    if len(branch_lengths) == 0:
        # fallback
        return poly.area / max(poly.length / 4.0, 1.0)

    return np.average(
        branch_depths,
        weights=branch_lengths,
    )

def main():

    print(f"Loading {INPUT_CSV}")

    df = pd.read_csv(INPUT_CSV)

    print(f"{len(df):,} buildings found")

    depths = df[
        GEOMETRY_COLUMN
    ].apply(calculate_average_depth)

    insert_position = (
        df.columns.get_loc("width_m") + 1
    )

    df.insert(
        insert_position,
        "average_depth_m",
        depths
    )

    df.to_csv(INPUT_CSV, index=False)

    print(
        "Finished. Added column: average_depth_m"
    )

if __name__ == "__main__":
    main()