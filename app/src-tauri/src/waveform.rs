use std::process::Command;
use std::path::{Path, PathBuf};
use serde::{Deserialize, Serialize};
use crate::process_utils::configure_command_no_window;

/// Resolves ffmpeg executable path from PATH or common bundled locations.
pub fn resolve_ffmpeg() -> Option<String> {
    if let Ok(output) = Command::new("ffmpeg").arg("-version").output() {
        if output.status.success() {
            return Some("ffmpeg".to_string());
        }
    }
    for candidate in &[
        "C:\\ffmpeg\\ffmpeg.exe",
        "binaries/ffmpeg.exe",
        "resources/binaries/ffmpeg.exe",
    ] {
        if Path::new(candidate).exists() {
            return Some(candidate.to_string());
        }
    }
    None
}

/// Resolves ffprobe executable path from PATH or common bundled locations.
pub fn resolve_ffprobe() -> Option<String> {
    if let Ok(output) = Command::new("ffprobe").arg("-version").output() {
        if output.status.success() {
            return Some("ffprobe".to_string());
        }
    }
    for candidate in &[
        "C:\\ffmpeg\\ffprobe.exe",
        "binaries/ffprobe.exe",
        "resources/binaries/ffprobe.exe",
    ] {
        if Path::new(candidate).exists() {
            return Some(candidate.to_string());
        }
    }
    None
}

/// Measures container PTS stretch vs decoded packet content duration (ms).
/// Essential for eliminating timing drift on long MP3/M4A Quran recitations.
#[tauri::command]
pub fn audio_timestamp_stretch_ms(file_path: String) -> Result<i64, String> {
    let path = Path::new(&file_path);
    if !path.exists() {
        return Err(format!("File not found: {}", file_path));
    }

    let ffprobe_path = resolve_ffprobe().ok_or_else(|| "ffprobe binary not found".to_string())?;

    let mut stream_cmd = Command::new(&ffprobe_path);
    stream_cmd.args([
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-count_packets",
        "-show_entries",
        "stream=codec_name,profile,sample_rate,nb_read_packets,duration",
        "-of",
        "default=noprint_wrappers=1",
        &file_path,
    ]);
    configure_command_no_window(&mut stream_cmd);
    let stream_out = stream_cmd
        .output()
        .map_err(|e| format!("Unable to execute ffprobe: {}", e))?;
    if !stream_out.status.success() {
        return Err(String::from_utf8_lossy(&stream_out.stderr).to_string());
    }

    let stdout = String::from_utf8_lossy(&stream_out.stdout);
    let mut codec_name = String::new();
    let mut profile = String::new();
    let mut sample_rate: f64 = 0.0;
    let mut packets: f64 = 0.0;
    let mut audio_duration_s: f64 = 0.0;
    for line in stdout.lines() {
        if let Some(v) = line.strip_prefix("codec_name=") {
            codec_name = v.trim().to_string();
        } else if let Some(v) = line.strip_prefix("profile=") {
            profile = v.trim().to_string();
        } else if let Some(v) = line.strip_prefix("sample_rate=") {
            sample_rate = v.trim().parse().unwrap_or(0.0);
        } else if let Some(v) = line.strip_prefix("nb_read_packets=") {
            packets = v.trim().parse().unwrap_or(0.0);
        } else if let Some(v) = line.strip_prefix("duration=") {
            audio_duration_s = v.trim().parse().unwrap_or(0.0);
        }
    }

    if sample_rate <= 0.0 || packets <= 0.0 || audio_duration_s <= 0.0 {
        return Ok(0);
    }

    let is_he_aac = profile.contains("HE");
    let samples_per_frame: f64 = match codec_name.as_str() {
        "aac" if is_he_aac => 2048.0,
        "aac" => 1024.0,
        "mp3" => 1152.0,
        "ac3" | "eac3" => 1536.0,
        "opus" => 960.0,
        _ => 1024.0,
    };

    let content_duration_s = packets * samples_per_frame / sample_rate;
    let stretch_s = audio_duration_s - content_duration_s;

    if stretch_s.abs() > audio_duration_s * 0.25 {
        return Ok(0);
    }

    Ok((stretch_s * 1000.0).round() as i64)
}

fn probe_audio_for_retime(file_path_str: &str) -> (String, String, u32, u32, u32, u32) {
    let empty = (String::new(), String::new(), 0u32, 0u32, 0u32, 0u32);
    let ffprobe_path = match resolve_ffprobe() {
        Some(p) => p,
        None => return empty,
    };
    let mut cmd = Command::new(&ffprobe_path);
    cmd.args([
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,profile,sample_rate,time_base,bit_rate",
        "-of",
        "default=noprint_wrappers=1",
        file_path_str,
    ]);
    configure_command_no_window(&mut cmd);
    let out = match cmd.output() {
        Ok(o) if o.status.success() => o,
        _ => return empty,
    };

    let stdout = String::from_utf8_lossy(&out.stdout);
    let mut codec = String::new();
    let mut profile = String::new();
    let mut sample_rate: u32 = 0;
    let mut tb_num: u32 = 0;
    let mut tb_den: u32 = 0;
    let mut bit_rate: u32 = 0;
    for line in stdout.lines() {
        if let Some(v) = line.strip_prefix("codec_name=") {
            codec = v.trim().to_string();
        } else if let Some(v) = line.strip_prefix("profile=") {
            profile = v.trim().to_string();
        } else if let Some(v) = line.strip_prefix("sample_rate=") {
            sample_rate = v.trim().parse().unwrap_or(0);
        } else if let Some(v) = line.strip_prefix("time_base=") {
            if let Some((n, d)) = v.trim().split_once('/') {
                tb_num = n.parse().unwrap_or(0);
                tb_den = d.parse().unwrap_or(0);
            }
        } else if let Some(v) = line.strip_prefix("bit_rate=") {
            bit_rate = v.trim().parse().unwrap_or(0);
        }
    }
    (codec, profile, sample_rate, tb_num, tb_den, bit_rate)
}

/// Normalizes audio timestamps in-place using FFmpeg asetpts/setts.
/// Eliminates cumulative audio-text drift on long recitation sessions.
#[tauri::command]
pub fn normalize_audio_timestamps(file_path: String) -> Result<(), String> {
    let path = Path::new(&file_path);
    if !path.exists() {
        return Err(format!("File not found: {}", file_path));
    }

    let ffmpeg_path = resolve_ffmpeg().ok_or_else(|| "ffmpeg binary not found".to_string())?;
    let extension = path
        .extension()
        .and_then(|ext| ext.to_str())
        .unwrap_or("mp4");
    let file_stem = path
        .file_stem()
        .and_then(|stem| stem.to_str())
        .unwrap_or("temp");
    let temp_path = if let Some(parent_dir) = path.parent() {
        parent_dir.join(format!("{}_retime_temp.{}", file_stem, extension))
    } else {
        PathBuf::from(format!("{}_retime_temp.{}", file_stem, extension))
    };
    let backup_path = if let Some(parent_dir) = path.parent() {
        parent_dir.join(format!("{}_retime_backup.{}", file_stem, extension))
    } else {
        PathBuf::from(format!("{}_retime_backup.{}", file_stem, extension))
    };

    let is_audio_only = matches!(
        extension.to_lowercase().as_str(),
        "mp3" | "wav" | "flac" | "aac" | "ogg" | "m4a" | "opus" | "weba"
    );

    let (codec_name, profile, sample_rate, tb_num, tb_den, source_bitrate) =
        probe_audio_for_retime(&file_path);
    if codec_name.is_empty() {
        return Ok(());
    }

    let samples_per_frame: u32 = if profile.contains("HE") { 2048 } else { 1024 };
    let can_lossless = codec_name == "aac"
        && !profile.contains("HE")
        && sample_rate > 0
        && tb_num == 1
        && tb_den == sample_rate;

    let temp_str = temp_path.to_string_lossy().to_string();
    let mut args: Vec<String> = vec!["-i".into(), file_path.clone()];

    if can_lossless {
        let setts = format!("setts=pts=N*{spf}:dts=N*{spf}", spf = samples_per_frame);
        if is_audio_only {
            args.extend(["-map", "0:a:0", "-c", "copy", "-bsf:a"].map(String::from));
            args.push(setts);
        } else {
            args.extend(
                ["-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-bsf:a"].map(String::from),
            );
            args.push(setts);
            args.extend(["-movflags", "+faststart"].map(String::from));
        }
    } else {
        let bitrate = if source_bitrate > 0 {
            source_bitrate.to_string()
        } else {
            "128k".to_string()
        };
        if is_audio_only {
            args.extend(["-map", "0:a:0", "-af", "asetpts=N/SR/TB", "-b:a"].map(String::from));
            args.push(bitrate);
        } else {
            args.extend(
                [
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-c:v",
                    "copy",
                    "-af",
                    "asetpts=N/SR/TB",
                    "-c:a",
                    "aac",
                    "-b:a",
                ]
                .map(String::from),
            );
            args.push(bitrate);
            args.extend(["-movflags", "+faststart"].map(String::from));
        }
    }
    args.push("-y".into());
    args.push(temp_str);

    let mut cmd = Command::new(&ffmpeg_path);
    cmd.args(&args);
    configure_command_no_window(&mut cmd);

    match cmd.output() {
        Ok(result) => {
            if result.status.success() {
                let _ = std::fs::remove_file(&backup_path);
                if std::fs::rename(path, &backup_path).is_ok() {
                    if std::fs::rename(&temp_path, path).is_ok() {
                        let _ = std::fs::remove_file(&backup_path);
                        Ok(())
                    } else {
                        let _ = std::fs::rename(&backup_path, path);
                        Err("Failed to replace original audio file after normalization".to_string())
                    }
                } else {
                    let _ = std::fs::remove_file(&temp_path);
                    Err("Failed to backup original audio file".to_string())
                }
            } else {
                let _ = std::fs::remove_file(&temp_path);
                let stderr = String::from_utf8_lossy(&result.stderr);
                Err(format!("FFmpeg audio normalization failed: {}", stderr))
            }
        }
        Err(e) => {
            let _ = std::fs::remove_file(&temp_path);
            Err(format!("Failed to execute FFmpeg: {}", e))
        }
    }
}

/// Extracts a simplified waveform peak array (100 peaks/sec normalized 0.0-1.0)
/// downsampled to 4kHz using FFmpeg (identical to QuranCaption commands::waveform).
#[tauri::command]
pub async fn get_audio_waveform(file_path: String) -> Result<Vec<f32>, String> {
    let path = Path::new(&file_path);
    if !path.exists() {
        return Err(format!("Audio file not found: {}", file_path));
    }

    let ffmpeg_bin = resolve_ffmpeg().ok_or_else(|| "FFmpeg binary not found on system".to_string())?;

    let mut cmd = Command::new(&ffmpeg_bin);
    cmd.args([
        "-i",
        &file_path,
        "-ac",
        "1",
        "-filter:a",
        "aresample=4000",
        "-map",
        "0:a",
        "-c:a",
        "pcm_s16le",
        "-f",
        "s16le",
        "-",
    ]);
    configure_command_no_window(&mut cmd);

    let output = cmd.output().map_err(|e| format!("Unable to execute ffmpeg: {}", e))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("FFmpeg error extracting waveform: {}", stderr));
    }

    let raw_data = output.stdout;
    let mut peaks = Vec::new();
    let samples_per_peak = 40; // 4000 Hz / 40 = 100 peaks per second
    let mut chunk_max = 0.0f32;
    let mut sample_count = 0;

    for chunk in raw_data.chunks_exact(2) {
        let sample = i16::from_le_bytes([chunk[0], chunk[1]]);
        let abs_sample = (sample as f32).abs() / 32768.0;
        if abs_sample > chunk_max {
            chunk_max = abs_sample;
        }
        sample_count += 1;
        if sample_count >= samples_per_peak {
            peaks.push(chunk_max);
            chunk_max = 0.0;
            sample_count = 0;
        }
    }
    if sample_count > 0 {
        peaks.push(chunk_max);
    }

    Ok(peaks)
}

/// Returns exact audio duration in milliseconds via ffprobe (matches QuranCaption commands::media::get_duration).
#[tauri::command]
pub fn get_duration(file_path: &str) -> Result<i64, String> {
    let path = Path::new(file_path);
    if !path.exists() {
        return Ok(-1);
    }

    let ffprobe_path = resolve_ffprobe().ok_or_else(|| "ffprobe binary not found".to_string())?;

    let mut cmd = Command::new(&ffprobe_path);
    cmd.args([
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        file_path,
    ]);
    configure_command_no_window(&mut cmd);

    match cmd.output() {
        Ok(result) => {
            if result.status.success() {
                let output_str = String::from_utf8_lossy(&result.stdout);
                let duration_line = output_str.trim();
                if let Ok(duration_seconds) = duration_line.parse::<f64>() {
                    Ok((duration_seconds * 1000.0).round() as i64)
                } else {
                    Err("Unable to parse duration from ffprobe output".to_string())
                }
            } else {
                let stderr = String::from_utf8_lossy(&result.stderr);
                Err(format!("ffprobe execution failed: {}", stderr.trim()))
            }
        }
        Err(e) => Err(format!("Unable to execute ffprobe: {}", e)),
    }
}

/// Fast lossless audio slice extraction using FFmpeg stream copy (matches QuranCaption commands::media::cut_audio).
#[tauri::command]
pub fn cut_audio(
    source_path: String,
    start_ms: u64,
    end_ms: u64,
    output_path: String,
) -> Result<(), String> {
    if !Path::new(&source_path).exists() {
        return Err(format!("Source file not found: {}", source_path));
    }

    let ffmpeg_path = resolve_ffmpeg().ok_or_else(|| "ffmpeg binary not found".to_string())?;
    let start_secs = start_ms as f64 / 1000.0;
    let duration_secs = (end_ms as f64 - start_ms as f64) / 1000.0;
    if duration_secs <= 0.0 {
        return Err("Duration must be positive".to_string());
    }

    let mut cmd = Command::new(&ffmpeg_path);
    cmd.args([
        "-ss",
        &start_secs.to_string(),
        "-t",
        &duration_secs.to_string(),
        "-i",
        &source_path,
        "-c",
        "copy",
        "-y",
        &output_path,
    ]);
    configure_command_no_window(&mut cmd);

    match cmd.output() {
        Ok(result) if result.status.success() => Ok(()),
        Ok(result) => {
            let stderr = String::from_utf8_lossy(&result.stderr);
            Err(format!("ffmpeg cut_audio error: {}", stderr.trim()))
        }
        Err(e) => Err(format!("Unable to execute ffmpeg: {}", e)),
    }
}

/// Diagnostic health status for multimedia binaries (ffmpeg, ffprobe).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BinaryDiagnosticResult {
    pub name: String,
    pub resolved_path: Option<String>,
    pub available: bool,
    pub version_output: Option<String>,
    pub error: Option<String>,
}

/// Diagnoses FFmpeg and FFprobe binary health, location, and version (matches QuranCaption commands::diagnostics).
#[tauri::command]
pub fn diagnose_media_binaries() -> Vec<BinaryDiagnosticResult> {
    let mut results = Vec::new();

    // Check FFmpeg
    let ffmpeg_path = resolve_ffmpeg();
    let (ffmpeg_avail, ffmpeg_ver, ffmpeg_err) = if let Some(ref p) = ffmpeg_path {
        let mut cmd = Command::new(p);
        cmd.arg("-version");
        configure_command_no_window(&mut cmd);
        match cmd.output() {
            Ok(output) if output.status.success() => {
                let stdout = String::from_utf8_lossy(&output.stdout);
                let first_line = stdout.lines().next().map(|l| l.trim().to_string());
                (true, first_line, None)
            }
            Ok(output) => {
                let stderr = String::from_utf8_lossy(&output.stderr);
                (false, None, Some(stderr.trim().to_string()))
            }
            Err(e) => (false, None, Some(e.to_string())),
        }
    } else {
        (false, None, Some("FFmpeg binary not found on PATH or bundled locations".to_string()))
    };
    results.push(BinaryDiagnosticResult {
        name: "ffmpeg".to_string(),
        resolved_path: ffmpeg_path,
        available: ffmpeg_avail,
        version_output: ffmpeg_ver,
        error: ffmpeg_err,
    });

    // Check FFprobe
    let ffprobe_path = resolve_ffprobe();
    let (ffprobe_avail, ffprobe_ver, ffprobe_err) = if let Some(ref p) = ffprobe_path {
        let mut cmd = Command::new(p);
        cmd.arg("-version");
        configure_command_no_window(&mut cmd);
        match cmd.output() {
            Ok(output) if output.status.success() => {
                let stdout = String::from_utf8_lossy(&output.stdout);
                let first_line = stdout.lines().next().map(|l| l.trim().to_string());
                (true, first_line, None)
            }
            Ok(output) => {
                let stderr = String::from_utf8_lossy(&output.stderr);
                (false, None, Some(stderr.trim().to_string()))
            }
            Err(e) => (false, None, Some(e.to_string())),
        }
    } else {
        (false, None, Some("FFprobe binary not found on PATH or bundled locations".to_string()))
    };
    results.push(BinaryDiagnosticResult {
        name: "ffprobe".to_string(),
        resolved_path: ffprobe_path,
        available: ffprobe_avail,
        version_output: ffprobe_ver,
        error: ffprobe_err,
    });

    results
}

/// Opens native file explorer highlighting the specified file (matches QuranCaption commands::media::open_explorer_with_file_selected).
#[tauri::command]
pub fn open_explorer_with_file_selected(file_path: String) -> Result<(), String> {
    let path = PathBuf::from(&file_path);
    if !path.exists() {
        return Err(format!("File not found: {}", file_path));
    }

    #[cfg(target_os = "windows")]
    {
        let mut cmd = Command::new("explorer");
        cmd.args(["/select,", &file_path]);
        configure_command_no_window(&mut cmd);
        return cmd
            .output()
            .map(|_| ())
            .map_err(|e| format!("Failed to execute explorer command: {}", e));
    }

    #[cfg(target_os = "macos")]
    {
        let mut cmd = Command::new("open");
        cmd.args(["-R", &file_path]);
        return cmd
            .output()
            .map(|_| ())
            .map_err(|e| format!("Failed to execute open command: {}", e));
    }

    #[cfg(target_os = "linux")]
    {
        let parent = path.parent().unwrap_or(&path);
        let mut cmd = Command::new("xdg-open");
        cmd.arg(parent);
        return cmd
            .output()
            .map(|_| ())
            .map_err(|e| format!("Failed to execute xdg-open command: {}", e));
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
    {
        Err("Unsupported operating system".to_string())
    }
}
