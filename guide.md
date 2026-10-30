## Executive summary {#summary}

The real-world failures come mainly from the radar data pipeline, not the model. Training and live data are captured with different radar settings, and the data stream that detects a still person is discarded in training and corrupted live.

### Key findings

1. **Train/serve skew.** All 13,191 training windows contain only points with |velocity| > 0.05 m/s, because RadarAnalysisTool exports had static-target removal on. The live script sends `mmwc cfar 0 8 0`, which turns static removal off and lowers the SNR threshold to 8 dB. Live data therefore contains walls, furniture and noise the model never saw.
2. **Micro-motion points are lost.** The SDK's micro-motion point cloud is the mechanism for detecting a seated, breathing person. `train.py` skips these files (`_mpc_`), and the live parser `psic_hif.py` most likely misreads them as shifted garbage.
3. **Reported accuracy is optimistic.** The split separates recordings but not days. Holding out one full day drops "non human" accuracy to 0% (Aug 14) and "fan" to 16–17%.
4. **Weak separating signal.** "Breathing only" and "non human" windows have nearly identical point counts, velocity and SNR. The model separates them using spatial spread, which depends on the room and sensor position.

### Top recommendations

1. Fix the parser and add a `PointType` column (motion / micro).
2. Freeze one radar configuration and save it with every recording.
3. Build features from micro-motion points and longer windows (5–10 s).
4. Collect empty-room data across days, rooms and positions; evaluate with leave-one-day-out and leave-one-room-out splits.
5. For deep learning, evaluate raw range-Doppler data (`mmwc report cube`) instead of the sparse point cloud.

## Radar fundamentals for ML engineers {#fundamentals}

The RS6240 is a 60 GHz FMCW radar with 2 transmit (TX) and 4 receive (RX) antennas. It measures range, radial velocity and angle of reflecting objects, then turns them into a point cloud on-chip. The MRS6240-P2512 module covers 57–66 GHz, sweeps up to 8 GHz, has a 120° horizontal and vertical field of view, and reaches about 20 m depending on target size.

**Chirps and frames.** The radar transmits a *chirp*: a tone whose frequency rises linearly over a short time. The echo is mixed with the transmitted chirp, producing a beat frequency proportional to distance. A *frame* is a burst of many chirps; frames repeat at the frame period (50 ms = 20 fps in your setup).

### Three measurements, three FFTs

| Quantity | How it is measured | What sets resolution | What sets the maximum |
| --- | --- | --- | --- |
| Range | FFT over samples within one chirp ("fast time") | Sweep bandwidth B: ΔR = c / 2B | ADC sample rate and chirp slope |
| Radial velocity | FFT across chirps in one frame ("slow time") | Frame active time: Δv = λ / (2·N·Tc) | Chirp repetition time: vmax = λ / (4·Tc) |
| Angle | Phase differences across the 8 virtual antennas | Number and layout of antennas | Antenna spacing (λ/2) |

Here c is the speed of light, λ is the wavelength (about 5.2 mm at 58 GHz), N is the number of chirp loops and Tc is the time between chirps from the same TX.

**MIMO.** With 2 TX and 4 RX transmitting in turn, the radar behaves like 8 virtual receivers. This gives azimuth and elevation angle, which is how each point gets x, y, z.

**Why a still person is hard.** Breathing moves the chest a few millimetres at a few mm/s. With your 0.2 m/s velocity resolution, that motion lands in the zero-velocity bin together with walls and furniture. Two mechanisms address this:

- **Static removal** discards zero-velocity reflections, removing furniture but also the still person.
- **Micro-motion point cloud** collects one sample every few frames over about 1.6 s and runs a second, much finer velocity FFT. This resolves millimetre-per-second motion such as breathing, so a still person appears while furniture does not.

**Detection (CFAR / SNR threshold).** The radar only reports a point when a range-velocity cell is brighter than the noise by a threshold. A lower threshold yields more points, including more noise; a higher threshold yields fewer but cleaner points.

## Map of the SDK and demo {#sdk-map}

Only a small part of the SDK (V2.0.6) matters for this project: the `mmwc` shell commands, the point-cloud and micro-motion algorithms, and the HIF message format. Most of the rest is firmware infrastructure.

### SDK: RS6x_7x_mmWave_sdk_V2.0.6/

| Path | What it is | Relevance |
| --- | --- | --- |
| `Hardware_Kit/01_Document/` | Datasheets, module specs, PCB guides (mostly Chinese) | Medium: RS6240 datasheet and MRS6240-P2512 module spec give band, FoV, range |
| `Software_Kit/01_Document/` | User manuals: RadarAnalysisTool, HIF format, host driver, SDK reference | High: tool manual defines every GUI parameter; host driver manual has the minimum frame period formula |
| `Software_Kit/02_SDK/psdf_sdk/subsys/mmw/mmw_cmd/src/mmw_shell.c` | Implementation of every `mmwc` command | High: ground truth for what your config commands do |
| `.../mmw_cmd/src/mmw_report.c` | Packs points into HIF 0xC3 messages | High: defines the wire format your parser must decode |
| `.../mmw_ctrl/inc/mmw_ctrl.h` | Documented API: mode, freq, range, velocity, frame | High: parameter limits and meaning |
| `.../mmw_application/mmw_app_pointcloud_config.c` | Default point-cloud settings | High: SDK defaults (static removal on, 12 dB) |
| `.../mmw_application/mmw_app_micro_pointcloud.c/.h` | Micro-motion point cloud | High: how still people are detected |
| `.../mmw_algorithm/` | CFAR, angle estimation (DOA), calibration | Medium |
| `Software_Kit/02_SDK/psdf_sdk/project/mmwave/` | Firmware projects: `mmw_point_cloud`, `radar_analysis`, `r3_databox`, `factory_test` | Medium: you run one of these images |
| `Software_Kit/03_Tool/RadarAnalysisTool/` | Windows GUI for configuring, viewing and recording | High: produced your training data; `lua/demoScript/MRS624x-*.lua` show vendor-recommended settings |
| `Software_Kit/03_Tool/RadarDebugTool/` | Raw ADC / data cube capture GUI (with `r3_databox` firmware) | Useful for future deep learning on raw data |
| `Software_Kit/04_Image/` | Prebuilt firmware images | `radar_analysis_6240_xip_cpuf.img` pairs with RadarAnalysisTool; `mmw_point_cloud_6240_cpuf.img` is the point-cloud demo |

### Your demo: rs6240_realtime_demo/

| Path | Role |
| --- | --- |
| `hardware/rs6240_spi_capture.py` | Sends `mmwc` config over UART, polls SPI, writes the live CSV |
| `hardware/psic_hif.py` | Decodes HIF frames and 0xC3 point payloads (contains the micro-point bug) |
| `hardware/ch347_spi.py` | Windows CH347 USB-SPI bridge wrapper |
| `src/rs6240_demo/preprocessing.py` | ROI crop and robust outlier filter |
| `src/rs6240_demo/features.py` | 35 window features, DBSCAN clustering |
| `src/rs6240_demo/inference.py` | EMA smoothing and hysteresis state machine |
| `train.py`, `build_model_from_windows.py` | Random Forest training and evaluation |
| `dashboard.py`, `dashboard_pages/` | Streamlit Replay / Mock / Live pages |
| `config.json` | Labels, ROI, window, inference thresholds |

**Firmware images.** `radar_analysis` firmware works with RadarAnalysisTool and can report points or the data cube. `mmw_point_cloud` is the standalone point-cloud demo; the `_pm` variants enable power management. `r3_databox` streams raw data to RadarDebugTool.

## Configuration parameters explained {#parameters}

The radar is configured over UART with `mmwc <command> <args>` shell commands, implemented in `mmw_shell.c`. Every command also accepts `get` (or no argument) to read back the current value. Configuration must happen between `mmwc open` and `mmwc start`, while the radar is stopped.

### Your current configuration

From `rs6240_spi_capture.py` (`MMWC_SETUP`).

| Command | Arguments | Meaning | Derived values for your setup |
| --- | --- | --- | --- |
| `mode 4 2` | txrx_mode, work_mode | 4 = 2T4R (8 virtual channels); 2 = 2D FFT (range + Doppler). Point cloud requires 2D FFT | Full azimuth + elevation |
| `freq 57000` | start_MHz [max_MHz] | Chirp start frequency; end frequency is derived from range resolution | Sweep ≈ 57.0–58.9 GHz (B = 1.875 GHz). Vendor scripts use 58000 |
| `range 20480 80` | max_mm, resolution_mm | Max unambiguous range and range bin size; ratio must be ≤ 1024 and ideally a power of 2 | 256 range bins; a 6 m room uses only ~75 |
| `veloc 3200 200` | max_mm/s, resolution_mm/s | Max unambiguous velocity and velocity bin size; 2·max/res ≤ 1024 | 32 Doppler bins; chirp loop ≈ 0.40 ms; ≈ 13 ms radar-on per frame |
| `dop_fft 1` | 0/1 | Run the Doppler FFT | On |
| `frame 50 0` | period_ms, frame_num | Frame period; 0 frames = run forever | 20 fps; frame duty ≈ 26% |
| `coord cart` | polar / cart | Point output as x,y,z (cart) or range/azimuth/elevation (polar) | Cartesian |
| `mount vertical` | vertical / horizon | Board orientation; selects antenna geometry for angle estimation. Ceiling mount is not supported | Must match physical mounting |
| `cfar 0 8 0` | static_rm, snr_dB, method | static_rm 1 removes Doppler bin 0 and ±1; snr = detection threshold in dB; method 0 = fixed SNR threshold, 1 = CA-CFAR | Static removal **off**, 8 dB. SDK default: on, 12 dB |
| `mpoint 1` | 0/1 | Enable micro-motion point cloud | On, but see parser bug |
| `comtype 1`, `hif_simplex 1`, `hif_retry 1` | — | Host interface transport settings for SPI | Transport only |
| `report points` | disable / cube / points / track | What the radar streams to the host | Point cloud |

### Derived timing

The host driver manual gives the per-loop chirp time t₁ (ms) for 2D FFT mode, with f_start in GHz and R_res in metres:

<div class="formula">t<sub>1</sub> = 3000 / ( V<sub>max</sub> · ( 40·f<sub>start</sub> + 3 / R<sub>res</sub> ) )</div>

For your settings: t₁ = 3000 / (3.2 × (2280 + 37.5)) ≈ 0.40 ms. Radar-on time per frame is t₁ × (2·V<sub>max</sub> / V<sub>res</sub>) = 0.40 × 32 ≈ 13 ms. The frame period must exceed this plus data reporting time; the release notes warn that too short a period causes a "data length incomplete" hang that needs a reset.

### Micro-motion point cloud commands

Available when the firmware is built with `CONFIG_MMW_MICRO_POINT_CLOUD`.

| Command | Arguments | Meaning | Default / your value |
| --- | --- | --- | --- |
| `mpoint` | 0/1 | Enable micro-motion points | 1 |
| `micro_snr` | 1–255 (linear) | Micro-Doppler detection threshold | 16 (≈ 18.5 dB effective per source comment); tool manual quotes 15 dB |
| `micro_station` | range_sta, dop_sta | Report only local peaks in range / micro-Doppler ("stationary-point filter") | Tool default: on |
| `micro_range` | min_mm, max_mm | Range gate for micro points | Full range; set to your room |
| `micro_angle` | az_min az_max [el_min el_max] (deg) | Angular gate for micro points | ±90° |
| `micro_frame` | sample_interval | Use every Nth frame as one micro-Doppler sample | Auto: round(200 ms / frame period) = 4 at 50 ms |

With 8 micro samples at 200 ms spacing, the micro-Doppler window spans 1.6 s. By the same physics as above, that gives roughly ±6.5 mm/s unambiguous velocity and about 1.6 mm/s resolution, which matches breathing chest motion.

### Other useful commands

| Command | Meaning |
| --- | --- |
| `clutter_rm <en> [fac]` | Continuous static clutter suppression on the raw data; fac 0–15, higher = slower background update. The SDK disables it when micro points are used |
| `clutter_halt <1/0>` | Freeze background clutter estimate |
| `win <0 range/1 doppler> <0 rect/1 hanning>` | FFT window type |
| `tx_rf_att <0–8>` | TX attenuation in dB; reduce for short rooms to avoid saturation |
| `rx_gain rf/dig <ant> <gain>` | Receiver gain; config comment recommends attenuation if max range < 5 m |
| `hpf <ant> <bw>` | Analog high-pass filter bandwidth (suppresses very close reflections) |
| `chirp_info`, `fft_len`, `getreportcfg` | Read back actual chirp parameters, FFT sizes, and data cube size |
| `noise est` | Run noise estimation |

Always log the output of `mmwc chirp_info`, `fft_len`, `cfar`, `mode` and `micro_snr` at the start of every recording.

## Signal processing chain: what the model actually sees {#signal-chain}

The model never sees raw radar signal. It sees a sparse list of detections that have already passed through FFTs, thresholds and filters on the chip, so every firmware setting changes the model's input distribution.

1. **Chirp and ADC.** Each RX samples the beat signal (10 or 20 MHz IF bandwidth).
2. **Range FFT** per chirp per antenna (hardware accelerator) → range bins.
3. **Doppler FFT** across chirp loops → a range-Doppler map per virtual antenna (the "data cube": 8 × 256 × 32 in your setup).
4. Two branches run on the same data:
    1. **Motion branch:** detection by SNR threshold or CA-CFAR (`cfar`), optional removal of Doppler bins 0 and ±1 (`static_rm`), extra direct-wave suppression in the first 200 mm, a cap of 768 detections, then angle estimation (DOA) across the 8 channels → motion points.
    2. **Micro-motion branch:** one sample stored every Nth frame (`micro_frame`), mean removal per range bin (clutter removal), 16-point micro-Doppler FFT over 8 samples, micro CFAR with optional stationary-peak filter (`micro_snr`, `micro_station`), digital beamforming for angle, range and angle gates → micro points. Up to 256 per update; updates arrive every 4th frame.
5. **Coordinate conversion** to x, y, z using the mount type.
6. **Reporting** over HIF (UART or SPI) as message 0xC3.

### HIF 0xC3 wire format

From `mmw_report.c`. Each frame is sent as one or more 0xC3 messages. Each message payload starts with a 12-byte frame header, followed optionally by a 4-byte TL header, then points.

| Field | Size | Content |
| --- | --- | --- |
| `frame_idx` | 4 B | Firmware frame counter (CSV FrameIndex = frame_idx + 1) |
| `frame_len` | 4 B | Total frame length in 32-bit words |
| `offset` | 4 B | Position of this message within the frame, in words |
| TL `type` | 1 B | 4 = points, 5 = tracked targets |
| TL `flag` | 1 B | bit0 = cartesian, bit1 = micro-motion |
| TL `length` | 2 B | Bytes of point data in this block |
| Point | 12 B each | x, y, z, velocity, SNR, uid as int16; units cm, cm/s, SNR × 100 |

The firmware sends the **motion block first** (TL header at offset 0) and then the **micro block as a separate message with its own TL header at a non-zero offset**. A single block larger than 3072 bytes (256 points) is split into continuation messages without a TL header.

### Consequences for ML

- Velocity is quantized to 0.2 m/s steps for motion points; with static removal on, the smallest reported speed is about 0.4 m/s.
- Micro points carry velocity on a completely different scale (mm/s). Mixing them with motion points without a type column corrupts velocity features.
- Point count per frame depends directly on the SNR threshold, static removal and range setting, so count-based features are not portable across configurations.

## Review of the current pipeline {#review}

The pipeline code is clean and well structured; the failures come from data capture and evaluation design. The current model (Random Forest, 35 features, 30-frame windows) reports 88.4% accuracy and 0.90 ROC AUC on a recording-level split, but 26% false-positive rate, driven by "fan" (48% false alarms).

### Dataset composition

31 recordings, 162 minutes, all about 5 minutes long, recorded on 6 days between Aug 12 and Sep 2, apparently in one room with one sensor position.

| Scenario | Label | Recordings | Minutes | Days recorded | Median points / frame |
| --- | --- | --- | --- | --- | --- |
| breathonly | occupied | 10 | 50.6 | Aug 12, 26, 31 | 7.0 |
| movement | occupied | 5 | 25.3 | Sep 2 only | 24.5 |
| fan and person | occupied | 5 | 27.2 | Aug 14, 31 | 17.1 |
| multiple people | occupied | 1 | 4.8 | Aug 24 only | 10.2 |
| non human | empty | 5 | 26.6 | Aug 14, 26 | 7.9 |
| fan | empty | 5 | 27.7 | Aug 14, 31 | 14.2 |

There is no plain empty-room scenario across multiple days, and several scenarios exist on a single day only.

### Finding 1: training and live data use different radar settings

- `moving_fraction_|v|>0.05` equals exactly 1.0 in all 13,191 windows. RadarAnalysisTool's static-target removal (removes Doppler bins 0 and ±1) was on when the training data was recorded.
- The live script sends `cfar 0 8 0`: static removal off, threshold 8 dB. The vendor demo scripts use static removal on and 12 dB.
- Effect: live windows contain zero-velocity clutter and more noise points. Point counts, SNR distribution, spatial spread and velocity features all shift relative to training.

### Finding 2: micro-motion points are discarded or corrupted

- `train.py` and the Replay dashboard skip files containing `_mpc_`, which are RadarAnalysisTool's micro-motion point cloud exports.
- In live capture, `parse_pointcloud_c3()` only reads a TL header when `offset == 0`. The micro block arrives at a non-zero offset with its own TL header, so the parser decodes the 4-byte header as point data. Every micro point is shifted by 4 bytes and becomes garbage, mixed into the same CSV, and the micro flag is never written.
- Also note: micro velocities are reported in integer cm/s, so most are 0 or ±1 cm/s. Use micro point presence, position and SNR rather than their velocity.

!!! warning "Verify on hardware"
    This is inferred from firmware source, not yet confirmed on hardware. Confirm by running the capture with `--debug` and checking for a second 0xC3 message per frame whose payload, after the 12-byte header, starts with `04 03`.

### Finding 3: evaluation leaks day-level conditions

I retrained the same Random Forest on `outputs/training_windows.csv`, holding out one full day at a time.

| Held-out day | Overall accuracy | Per-scenario accuracy |
| --- | --- | --- |
| Aug 14 | 29% | non human 0%, fan 17%, fan and person 100% |
| Aug 31 | 60% | fan 16%, fan and person 81%, breathonly 100% |
| Aug 26 | 94% | breathonly 96%, non human 80% |
| Aug 12, Aug 24, Sep 2 | 98–100% | single-scenario days (occupied only) |

Empty-room classes collapse on unseen days: the model calls empty rooms occupied. This matches the real-world symptom of false alarms. Caveat: holding out Aug 14 leaves only one "non human" recording for training, so part of the drop is data scarcity, which is itself a finding.

### Finding 4: the features that matter are room-specific

| Scenario | Points / frame | Mean abs velocity (m/s) | Median SNR (dB) | y span (m) |
| --- | --- | --- | --- | --- |
| breathonly | 7.0 | 0.40 | 13.8 | 4.05 |
| non human | 7.9 | 0.40 | 14.1 | 0.88 |
| fan | 14.2 | 1.02 | 14.7 | 1.34 |

"Breathing only" and "non human" are indistinguishable except for spatial spread. The top features by importance are `y_span`, `x_std`, `range_p90` and `range_mean`. These depend on room size, furniture and sensor placement, so they do not transfer to a new room.

### Smaller issues

- **Robust outlier filter skew:** in training, MAD statistics are computed over the whole recording; live uses the last 300 frames. The README already flags this.
- **Short windows:** 30 frames = 1.5 s, shorter than one micro-motion window (1.6 s) and one breathing cycle (3–5 s).
- **Absolute position features** (`x_mean`, `y_mean`, `centroid_motion_proxy`) tie the model to one sensor placement.
- **Missing frames:** `make_windows` assumes contiguous frame indices; dropped SPI frames reduce effective window length silently.

### Parser fix (sketch)

Track the remaining bytes of the current TL block per frame, and read a new TL header whenever the previous block is exhausted. This handles motion blocks, continuation messages and the micro block.

```python
class C3FrameAssembler:
    """Stateful decoder for HIF 0xC3 payloads (motion + micro blocks)."""

    def __init__(self):
        self.state = {}  # frame_idx -> dict

    def feed(self, payload: bytes):
        frame_idx = int.from_bytes(payload[0:4], "little")
        offset = int.from_bytes(payload[8:12], "little")
        rest = payload[12:]
        st = self.state.setdefault(frame_idx, {"remaining": 0, "cart": True, "micro": False, "next_pi": 0})
        if offset == 0:
            st.update(remaining=0, next_pi=0)
        points = []
        while rest:
            if st["remaining"] == 0:  # a new TL block starts here
                if len(rest) < 4:
                    break
                flag = rest[1]
                st.update(remaining=int.from_bytes(rest[2:4], "little"),
                          cart=bool(flag & 0x1), micro=bool(flag & 0x2))
                rest = rest[4:]
                continue
            n = min(len(rest), st["remaining"])
            n -= n % 12
            if n == 0:
                break
            body, rest = rest[:n], rest[n:]
            st["remaining"] -= n
            decode = _points_from_cart if st["cart"] else _points_from_polar
            pts = decode(body, frame_idx, st["next_pi"])
            for p in pts:
                p.micro = st["micro"]
            st["next_pi"] += len(pts)
            points.extend(pts)
        return frame_idx, points
```

Then add a `PointType` column (`motion` / `micro`) to `CSV_FIELDS`, and drop old frame entries from `self.state` to bound memory. In `rs6240_spi_capture.py`, keep the duplicate check (`offset == 0 and csv_idx in frames_seen`), since `hif_retry 1` can resend messages, but move it into the assembler so retried continuation messages are also de-duplicated.

## Parameter tuning guide {#tuning}

Use static removal on for the motion points and rely on micro-motion points for still people. This gives two clean, complementary signals: motion points for walking, gesturing and fans; micro points for seated, sleeping or breathing people. Fix the configuration first, then collect data; any later change means re-collecting or re-validating.

### Recommended starting configuration

Assumes a room up to about 6 m deep. Validate on hardware: if any command returns an error code, relax that parameter, then read back actual values with `mmwc chirp_info` and `mmwc fft_len`.

```bash
mmwc stop
mmwc close
mmwc open
mmwc mode 4 2              # 2T4R, range + Doppler
mmwc freq 58000            # vendor default start frequency
mmwc range 6400 50         # 6.4 m, 5 cm bins -> 128 range bins (B = 3 GHz)
mmwc veloc 1600 100        # +/-1.6 m/s, 0.1 m/s bins -> 32 Doppler bins
mmwc dop_fft 1
mmwc frame 100 0           # 10 fps; radar-on ~25 ms per frame
mmwc coord cart
mmwc mount vertical        # must match physical mounting
mmwc cfar 1 12 0           # static removal ON, 12 dB, SNR threshold
mmwc mpoint 1              # micro-motion points ON
mmwc micro_range 300 6000  # gate micro points to the room
mmwc micro_station 1 1     # stationary-peak filter (tool default)
mmwc comtype 1
mmwc hif_simplex 1
mmwc hif_retry 1
mmwc report points
mmwc start
```

Why these values: 128 range bins cover the room with finer resolution and fewer empty bins. Halving the velocity resolution to 0.1 m/s lowers the smallest speed that survives static removal to about 0.2 m/s, so slow movements still produce motion points. 10 fps halves data volume with no loss for occupancy decisions; the micro-motion sampler auto-adjusts to every 2nd frame, keeping its 1.6 s window. If people walk fast toward the sensor, keep `veloc 3200 200` to avoid velocity aliasing.

### What each parameter trades off

| Parameter | Increase it | Decrease it | Occupancy guidance |
| --- | --- | --- | --- |
| Max range (`range` arg 1) | Covers larger rooms; more bins to process | Fewer wasted bins; less multipath from beyond the room | Room depth + 0.5 m |
| Range resolution (`range` arg 2) | Coarser, fewer bins | Separates nearby people; wider sweep | 4–8 cm |
| Max velocity (`veloc` arg 1) | Captures fast motion without aliasing | Longer chirp time, finer velocity | 1.6–3.2 m/s |
| Velocity resolution (`veloc` arg 2) | Shorter radar-on time | Slow motion leaves the static bins; longer radar-on time | 0.1–0.2 m/s |
| Frame period (`frame`) | Less data, lower power, longer micro sampling step | Smoother tracking | 50–100 ms; define ML windows in seconds, not frames |
| SNR threshold (`cfar` arg 2) | Fewer, cleaner points; may miss weak targets | More points, more noise | 10–14 dB; sweep it |
| Static removal (`cfar` arg 1) | Removes furniture and still people | Keeps everything; model must learn each room's clutter | On, with micro points |
| CFAR method (`cfar` arg 3) | 1 = CA-CFAR adapts to local noise; better in cluttered rooms | 0 = fixed threshold, simpler | Test both |
| `micro_snr` | Fewer false micro points (fans, curtains) | Detects shallower breathing | Sweep around default 16 |
| `micro_range`, `micro_angle` | — | Excludes doors, windows, fans outside the area of interest | Gate to the occupied zone |
| `tx_rf_att`, `rx_gain` | — | Avoids saturation in small rooms | Try if near-range points are noisy |

### Tuning procedure

1. Fix sensor mounting height, tilt and position, and photograph the setup.
2. Record a scripted session per configuration: 3 min empty, 3 min fan only, 3 min seated still, 3 min moving, and enter/exit transitions.
3. For each configuration, plot per-frame motion and micro point counts over time, coloured by scenario.
4. Pick settings that maximise the separation between "empty / fan only" and "seated still" on the micro channel, and between "empty" and "moving" on the motion channel.
5. Change one parameter at a time and save the full `mmwc` command list with every recording.

### Sweep plan

| Experiment | Values | Watch |
| --- | --- | --- |
| SNR threshold | 8, 10, 12, 14 dB | Empty-room points / frame vs moving-person points / frame |
| CFAR method | 0, 1 | False points near walls and furniture |
| `micro_snr` | 8, 12, 16, 24 | Micro points: seated person vs empty vs fan |
| `micro_station` | (1,1), (0,0) | Micro point count and spatial spread |
| Velocity resolution | 0.2, 0.1 m/s | Motion points from slow movement (typing, turning) |
| Frame period | 50, 100 ms | Detection delay after entry; data rate |

## ML/DL pipeline improvements {#ml-pipeline}

The biggest gains will come from data diversity and evaluation design, not model choice. A Random Forest on the right features, trained on varied data and validated on unseen rooms, will beat a deep model trained on one room.

### Data collection protocol

- **One capture path.** Record training data with the same script and configuration used in deployment, with the `PointType` column and a JSON sidecar holding the full `mmwc` command list, firmware image, sensor position, room, and notes.
- **Diversity axes**, each varied deliberately: at least 3 rooms; 2–3 sensor positions and heights per room; multiple days; people of different sizes; different postures (sitting, lying, standing still, typing); and distractors (fan, curtains, plants, pets, robot vacuum, monitor, AC vents).
- **Plain empty room** on every day and in every room. This is the most important negative class and currently has no dedicated scenario.
- **Long continuous sessions** (30–60 min) with real transitions, labelled by timestamps, not one-condition 5-minute clips. Transitions are where a deployed system fails.
- **Ground truth:** log occupancy changes with a button, a phone app or a webcam timestamp, kept separate from radar data.
- **Target size:** at least 20 hours across 3+ rooms before trusting any metric.

### Features that transfer across rooms

Replace absolute geometry with signals that describe human presence regardless of room.

| Feature group | Examples | Why it transfers |
| --- | --- | --- |
| Micro-motion presence | Micro points per update, fraction of updates with any micro point, micro SNR | Breathing produces micro points; furniture does not |
| Spatial persistence | Size of the densest micro cluster that persists > N seconds; dwell time in one spot | People stay put; noise jumps around |
| Motion energy | Motion points / s, Doppler spread, fraction of frames with motion | Describes activity, not room shape |
| Periodicity | Spectral peak at 0.1–0.5 Hz (breathing) in micro point counts or SNR at the persistent cluster | Separates people from fans (higher, steady frequencies) |
| Baseline-relative | Each feature minus its value from an empty-room calibration recording | Cancels room-specific clutter |

Use windows of 5–10 s with 1 s stride, defined in seconds, so the model is independent of frame rate.

### Model options, in order

1. **Gradient boosting or Random Forest on transferable features.** Fast, interpretable, good baseline; use feature importance and SHAP to check that room geometry is not dominating.
2. **Temporal model on per-frame summaries.** Per-frame vectors (counts, SNR, Doppler histogram, occupancy grid of micro points) fed to a 1D CNN, GRU or small transformer over 10–30 s. Captures breathing rhythm and entry/exit dynamics.
3. **Point-cloud deep learning.** PointNet-style per-frame encoder plus a temporal model. Only worth it with many hours of diverse data.
4. **Raw data deep learning.** Switch to `mmwc report cube` and train a CNN on range-Doppler maps or range profiles over slow time. Richest input, since nothing is discarded by thresholds. With the recommended config the cube is 8 × 128 × 32 × 4 B = 131 KB per frame (1.3 MB/s at 10 fps). The host manual estimates SPI reporting at about 22 ms per frame for these settings, and release notes cite 64 kB at 50 Hz for the SPI host sample. Verify on hardware; reduce bins if needed.

### Evaluation

- **Splits:** leave-one-day-out and leave-one-room-out. Never let recordings from the same day and room appear in both train and test.
- **Window metrics:** balanced accuracy, ROC AUC, false-positive rate per scenario.
- **System metrics** (on continuous sessions, after smoothing and hysteresis): false alarms per hour when empty; miss duration while a still person is present; detection delay after entry; clearance delay after exit.
- **Calibration check:** reliability plot of predicted probabilities, so the hysteresis thresholds (0.65 / 0.35) mean what they should.

### Decision logic

- Use asymmetric timing: declare occupied quickly on motion, but require a long absence of both motion and micro points (for example 30–60 s) before declaring empty. Still people produce intermittent evidence.
- Combine a learned probability with simple rules, such as "any persistent micro cluster for > 10 s keeps the room occupied".

### Engineering hygiene

- Make preprocessing identical in training and live: fixed ROI and SNR filters, or rolling statistics computed the same way in both.
- Version datasets (DVC or a manifest with hashes) and store config sidecars with every recording.
- Add a unit test that parses a captured binary dump and checks motion and micro point counts against RadarAnalysisTool's export of the same session.

## Setting up Claude for this project {#claude}

Run Claude Code on the Windows PC that has the radar attached. There it can read the SDK, edit the capture and training code, run captures on real hardware, retrain, and report results. Use the chat app for discussion and documents like this one.

### Which Claude surface for which job

| Job | Surface | Why |
| --- | --- | --- |
| Edit code, run captures, train, evaluate | Claude Code (terminal, VS Code, or the desktop app's Code tab) | Direct access to files, Python, COM ports and the sensor |
| Unattended jobs (nightly retraining, config sweeps) | Claude Code desktop scheduled tasks | Run on your machine with local files and tools |
| Repo-wide automation (PR review, issue triage) | Claude Code GitHub Actions | Runs in CI on every pull request |
| Team discussion, research, documents | Claude chat with this guide | Shared, commentable reference |

### Step 1: install Claude Code on the radar PC

In Windows PowerShell:

```powershell
irm https://claude.ai/install.ps1 | iex
claude --version
cd C:\path\to\rs6240_realtime_demo
claude
```

Install Git for Windows so Claude Code can use its Bash tool; without it, Claude Code falls back to PowerShell. Because the CH347 wrapper uses `ctypes.windll`, run Claude Code natively on Windows rather than in WSL for hardware work.

### Step 2: put the project in one repository

```text
rs6240-occupancy/
├── CLAUDE.md            # project instructions Claude reads every session
├── docs/                # this guide, SDK notes, extracted manual text
├── sdk_ref/             # only the relevant SDK sources (mmw_shell.c, mmw_report.c, mmw_ctrl.h, micro pointcloud)
├── radar_configs/       # one .txt per named mmwc config
├── hardware/            # capture + parser
├── src/                 # preprocessing, features, models
├── data/                # recordings + JSON sidecars (gitignored, versioned with DVC)
└── experiments/         # one folder per run: config, metrics, plots
```

The SDK manuals are mostly Chinese PDFs. Ask Claude Code to extract the relevant chapters to English markdown in `docs/` once, so every later session can search them.

### Step 3: write a CLAUDE.md

CLAUDE.md is a markdown file at the project root that Claude Code reads at the start of every session. Starter version:

```markdown
# RS6240 occupancy detection

## Goal
Binary room occupancy (empty / occupied) from an RS6240 60 GHz radar, robust across rooms.

## Hardware
- MRS6240-P2512 module, 2T4R, Windows PC, UART (config) + CH347 SPI (data).
- Capture: `python hardware/rs6240_spi_capture.py --port COM10 --config radar_configs/<name>.txt`
- Never flash firmware or change COM/driver settings without asking me.

## Data rules
- CSV columns: FrameIndex, PointIndex, X, Y, Z, Velocity, SNR, PointType (motion|micro).
- Every recording has a JSON sidecar: mmwc config, room, sensor position, labels with timestamps.
- Never mix recordings made with different radar configs in one training set.
- Never modify files under data/raw/.

## Evaluation rules
- Splits are leave-one-day-out and leave-one-room-out. Never split by window or recording alone.
- Report: balanced accuracy, per-scenario FPR, false alarms per hour, still-person miss duration.
- Save each run to experiments/<date>_<name>/ with config, metrics.json and plots.

## Reference
- docs/rs6240_guide.md: radar parameters, firmware wire format, known issues.
- sdk_ref/: firmware source for mmwc commands and the 0xC3 format.
```

### Step 4: connect tools (MCP)

Claude Code connects to external tools through MCP servers, for example Google Drive for shared docs, Jira or Linear for tickets, and Slack for team updates. Add only what you need, such as GitHub for the repo and your team's tracker.

### Step 5: automate

- **Skills** package repeatable workflows as slash commands. Useful ones: `/capture-session` (run a scripted capture with a named config and write the sidecar), `/evaluate` (run leave-one-day/room-out and write a report), `/sweep` (loop over configs from the sweep plan).
- **Hooks** run commands before or after Claude's actions, for example running `pytest` on the parser after any edit to `hardware/`.
- **Headless mode** (`claude -p "..."`) lets scripts call Claude, for example: `claude -p "Run /evaluate on the newest recordings and summarise regressions"`.
- **Scheduled tasks** can run that nightly on the radar PC.
- **GitHub Actions** can review every pull request against the CLAUDE.md rules.

### Suggested first tasks for Claude Code

1. "Implement the C3FrameAssembler from docs/rs6240_guide.md, add a PointType column, and add a test using a captured --debug dump."
2. "Make the capture script read the mmwc command list from radar_configs/ and save it in a JSON sidecar."
3. "Rewrite train.py to run leave-one-day-out evaluation and output per-scenario metrics."
4. "Add transferable features (micro presence, persistence, breathing periodicity) and compare against the current feature set."

Keep a human in the loop for anything touching hardware: review each command list before a sweep starts.

## Roadmap and open questions {#roadmap}

### Roadmap

Tick items as your team completes them; ticks are saved in your browser.

- [ ] **Phase 1: fix the data path (about 1 week).** Fix the parser and add `PointType`; confirm the micro-block bug with a `--debug` dump; move radar configs into files saved with each recording; compare one session captured by both RadarAnalysisTool and the script.
- [ ] **Phase 2: choose the radar configuration (1–2 weeks).** Run the sweep plan in one room with scripted sessions; freeze a configuration.
- [ ] **Phase 3: re-collect data (2–4 weeks).** 3+ rooms, multiple positions and days, long continuous labelled sessions, an empty-room recording every day.
- [ ] **Phase 4: model (1–2 weeks).** Transferable features, 5–10 s windows, leave-one-room-out evaluation, system-level metrics.
- [ ] **Phase 5: optional deep learning.** Data cube capture and range-Doppler CNN once Phase 4 sets a baseline.

### Open questions

- What radar settings were used in RadarAnalysisTool for the existing training recordings? The `moving_fraction` evidence shows static removal was on; SNR threshold and start frequency are unknown.
- Is the sensor wall-mounted or ceiling-mounted in the target deployment? The firmware supports vertical and horizontal mounting only; ceiling is not supported.
- What room sizes and layouts must the product handle?
- What error matters more to the product: false alarms or missed occupants?
- Do the `_mpc_` exports exist for the existing recordings? If so, micro features can be evaluated on current data immediately.

## Glossary {#glossary}

| Term | Meaning |
| --- | --- |
| FMCW | Frequency-modulated continuous wave: radar that sends rising-frequency chirps |
| Chirp | One linear frequency sweep |
| Frame | A burst of chirps, processed into one point cloud |
| 2T4R / MIMO | 2 transmitters × 4 receivers = 8 virtual antennas |
| Range FFT / Doppler FFT | FFTs giving distance and radial velocity |
| Data cube | Range × Doppler × antenna array before detection |
| CFAR | Constant false alarm rate detection; adaptive threshold |
| SNR threshold | Fixed detection threshold relative to noise |
| Static removal | Discarding zero-velocity (and ±1 bin) detections |
| Micro-motion point cloud | Points from a slow, fine-velocity FFT across frames; detects breathing |
| DOA / DBF | Direction-of-arrival estimation / digital beamforming for angle |
| HIF | Host interface protocol between radar and PC (UART or SPI) |
| 0xC3 | HIF message ID carrying point-cloud data |
| TL header | 4-byte type/flag/length header before each point block |

## Sources {#sources}

- SDK V2.0.6 firmware source: `subsys/mmw/mmw_cmd/src/mmw_shell.c`, `mmw_report.c`, `mmw_ctrl/inc/mmw_ctrl.h`, `mmw_application/mmw_app_pointcloud_config.c`, `mmw_app_micro_pointcloud.c/.h`.
- RS6240 datasheet V1.4 and MRS6240-P2512 module specification V1.0.
- RadarAnalysisTool user manual V1.2 (parameter definitions) and `lua/demoScript/MRS624x-*.lua` (vendor settings).
- R3 HOST driver development manual V1.1, Q&A 7.2.1 (minimum frame period formula).
- Demo project `rs6240_realtime_demo`: `outputs/training_windows.csv`, `recording_summary.csv`, `split_manifest.csv`, `model_metrics.json`.
- [Claude Code overview](https://code.claude.com/docs/en/overview.md): install, CLAUDE.md, MCP, skills, hooks, headless mode, scheduled tasks, GitHub Actions.
