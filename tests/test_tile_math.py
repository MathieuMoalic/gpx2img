from gpx2img.core import Bounds, expand_bounds, latlon_to_tile, tiles_for_bounds


def test_known_tile_coordinate() -> None:
    x, y = latlon_to_tile(49.629944, 19.757944, 11)
    assert x == 1136
    assert y == 697


def test_tiles_for_babia_bounds() -> None:
    bounds = Bounds(
        min_lat=49.55,
        min_lon=19.45,
        max_lat=49.65,
        max_lon=19.80,
    )
    tiles = tiles_for_bounds(bounds, 11)
    assert (1134, 698) in tiles
    assert (1135, 698) in tiles


def test_expand_bounds_increases_area() -> None:
    src = Bounds(49.6, 19.7, 49.61, 19.71)
    dst = expand_bounds(src, 1.0)
    assert dst.min_lat < src.min_lat
    assert dst.min_lon < src.min_lon
    assert dst.max_lat > src.max_lat
    assert dst.max_lon > src.max_lon

