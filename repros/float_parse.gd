extends SceneTree
## Repro for Godot issues 123700 (leading zeros) and 124516 (rounding, DBL_MIN).
## Run: godot --headless --path repros -s float_parse.gd
## Deterministic: fixed seed, so two machines parse the same strings.

const SAMPLES := 20000


func _init() -> void:
	print("engine ", Engine.get_version_info().string, " on ", OS.get_name())

	# 1. Leading zeros count against the 18-digit limit (#123700).
	var lead := "00000000000000000001.5"
	print("leading zeros: \"%s\".to_float() = %s (expect 1.5)" % [lead, lead.to_float()])
	print("leading zeros: float(\"%s\") = %s (expect 1.5)" % [lead, float(lead)])

	# 2. Smallest normal double reads as 0 (#124516).
	var dbl_min := "2.2250738585072014e-308"
	var got := dbl_min.to_float()
	print("DBL_MIN: \"%s\".to_float() = %s, is zero: %s (expect not zero)" % [dbl_min, got, got == 0.0])

	# 3. Round trip of random finite doubles through String.num_scientific (#124516).
	var rng := RandomNumberGenerator.new()
	rng.seed = 123700
	var bytes := PackedByteArray()
	bytes.resize(8)
	var tried := 0
	var off := 0
	var example := ""
	while tried < SAMPLES:
		for i in 8:
			bytes[i] = rng.randi() & 0xFF
		var x := bytes.decode_double(0)
		if is_nan(x) or is_inf(x):
			continue
		tried += 1
		var s := String.num_scientific(x)
		var y := s.to_float()
		if y != x:
			off += 1
			if off <= 50:  # for checking against a correct parser (check_mismatches.py)
				var yb := PackedByteArray()
				yb.resize(8)
				yb.encode_double(0, y)
				print("MM ", bytes.hex_encode(), " ", s, " ", yb.hex_encode())
			if example.is_empty():
				example = "%s parsed back as %s" % [s, String.num_scientific(y)]
	print("round trip: %d of %d random doubles came back different (%.1f%%)" % [off, tried, 100.0 * off / tried])
	if not example.is_empty():
		print("first mismatch: ", example)
	quit()
