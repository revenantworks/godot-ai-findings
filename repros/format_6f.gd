extends SceneTree
## Probe for finding 3: does "%.6f" % x print the same text on Windows and Linux?
## Run on both platforms and diff the outputs:
##   godot --headless --path repros -s format_6f.gd > out-<os>.txt
## Deterministic: fixed seed, values in the range a game position takes.

const SAMPLES := 200000


func _init() -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = 6
	var bytes := PackedByteArray()
	bytes.resize(8)
	for i in SAMPLES:
		var x: float
		if i % 2 == 0:
			x = rng.randf_range(-10000.0, 10000.0)  # position-like values
		else:
			# a decimal ending in 5 at the 7th place: the hardest case for rounding
			x = (rng.randi_range(-1000000000, 1000000000) * 10 + 5) / 1e7
		bytes.encode_double(0, x)
		print(bytes.hex_encode(), " ", "%.6f" % x)
	quit()
