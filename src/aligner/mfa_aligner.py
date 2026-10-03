"""Phase 5 (Optional): Montreal Forced Aligner (MFA) Integration Engine.

Provides high-precision 10ms phone-level and letter-level acoustic forced alignment
using the Hafs riwaya acoustic model and pronunciation dictionary.
Operates as an independent, non-intrusive add-on module.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import logging
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
import scipy.io.wavfile as wavfile

import config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DATA MODELS FOR MFA ALIGNMENT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class MfaPhone:
    """Individual phone/letter timing produced by Montreal Forced Aligner."""
    phone: str
    start: float
    end: float
    duration: float
    rule: Optional[str] = None
    golden_len: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "phone": self.phone,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
        }
        if self.rule is not None:
            d["rule"] = self.rule
        if self.golden_len is not None:
            d["golden_len"] = self.golden_len
        return d


@dataclass(slots=True)
class MfaWord:
    """Word-level timing and constituent phones from MFA TextGrid."""
    word: str
    start: float
    end: float
    duration: float
    phones: List[MfaPhone] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "phones": [p.to_dict() for p in self.phones],
            "phonemes": [
                {
                    "phoneme": p.phone,
                    "start": round(p.start, 3),
                    "end": round(p.end, 3),
                    **({"rule": p.rule} if p.rule else {}),
                    **({"golden_len": p.golden_len} if p.golden_len else {}),
                }
                for p in self.phones
            ],
        }


@dataclass(slots=True)
class MfaAyahResult:
    """Aligned Ayah result with words, letters, and Tajweed rule annotations."""
    surah: int
    ayah: int
    start_time: float
    end_time: float
    words: List[MfaWord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ayah": self.ayah,
            "surah": self.surah,
            "start": round(self.start_time, 3),
            "end": round(self.end_time, 3),
            "duration": round(self.end_time - self.start_time, 3),
            "segments": [
                {
                    "segment": 1,
                    "start": round(self.start_time, 3),
                    "end": round(self.end_time, 3),
                    "words": [w.to_dict() for w in self.words],
                }
            ],
            "words": [w.to_dict() for w in self.words],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ZERO-DEPENDENCY PRAAT TEXTGRID PARSER
# ═══════════════════════════════════════════════════════════════════════════════

def parse_praat_textgrid(filepath: str) -> Dict[str, List[Tuple[float, float, str]]]:
    """Lightweight, robust parser for Praat IntervalTiers without third-party dependencies."""
    tiers: Dict[str, List[Tuple[float, float, str]]] = {}
    if not os.path.exists(filepath):
        return tiers

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = [line.strip() for line in f]

    current_tier_name = None
    in_interval = False
    cur_xmin: Optional[float] = None
    cur_xmax: Optional[float] = None
    cur_text: Optional[str] = None

    i = 0
    num_lines = len(lines)
    while i < num_lines:
        line = lines[i]
        if line.startswith('class = "IntervalTier"'):
            # Next line usually contains name
            i += 1
            if i < num_lines and lines[i].startswith('name ='):
                current_tier_name = lines[i].split("=")[-1].strip().strip('"')
                tiers[current_tier_name] = []
        elif current_tier_name and line.startswith("intervals ["):
            in_interval = True
            cur_xmin, cur_xmax, cur_text = None, None, None
        elif in_interval:
            if line.startswith("xmin ="):
                try:
                    cur_xmin = float(line.split("=")[-1].strip())
                except ValueError:
                    pass
            elif line.startswith("xmax ="):
                try:
                    cur_xmax = float(line.split("=")[-1].strip())
                except ValueError:
                    pass
            elif line.startswith("text ="):
                raw_text = line[line.find("=") + 1:].strip().strip('"')
                cur_text = raw_text
                if cur_xmin is not None and cur_xmax is not None:
                    # Ignore silence intervals labeled "", "<eps>", or "sil"
                    if cur_text not in ("", "<eps>", "sil", "sp"):
                        tiers[current_tier_name].append((cur_xmin, cur_xmax, cur_text))
                in_interval = False
        i += 1

    return tiers


# ═══════════════════════════════════════════════════════════════════════════════
# 3. RULE INDEX LOADER
# ═══════════════════════════════════════════════════════════════════════════════

def load_tajweed_rule_index(rule_index_path: str) -> Dict[Tuple[int, int], List[Dict[str, Any]]]:
    """Loads per-ayah Tajweed rule annotations from rule_index.jsonl."""
    rule_map: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    if not os.path.exists(rule_index_path):
        logger.warning(f"Tajweed rule index not found at: {rule_index_path}")
        return rule_map

    with open(rule_index_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                s = entry.get("surah")
                a = entry.get("ayah")
                phones = entry.get("phones", [])
                if s is not None and a is not None:
                    rule_map[(s, a)] = phones
            except Exception:
                continue

    return rule_map


# ═══════════════════════════════════════════════════════════════════════════════
# 4. MFA ALIGNMENT ENGINE & ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

class QuranMfaAligner:
    """Independent Montreal Forced Aligner interface for high-precision phoneme timing."""

    def __init__(
        self,
        mfa_dir: Optional[str] = None,
        acoustic_model_path: Optional[str] = None,
        dict_path: Optional[str] = None,
        rule_index_path: Optional[str] = None,
    ):
        base_dir = mfa_dir or getattr(
            config,
            "DEFAULT_MFA_DIR",
            Path(getattr(config, "DATA_PATH", "data")) / "mfa",
        )
        self.acoustic_model = acoustic_model_path or getattr(
            config, "DEFAULT_MFA_ACOUSTIC_PATH", str(Path(base_dir) / "quran_hafs_acoustic.zip")
        )
        self.dictionary = dict_path or getattr(
            config, "DEFAULT_MFA_DICT_PATH", str(Path(base_dir) / "quran_hafs.dict")
        )
        self.rule_index_path = rule_index_path or getattr(
            config, "DEFAULT_MFA_RULES_PATH", str(Path(base_dir) / "rule_index.jsonl")
        )
        self._rule_cache: Optional[Dict[Tuple[int, int], List[Dict[str, Any]]]] = None

    @classmethod
    def find_micromamba_executable(cls) -> Optional[str]:
        """Locates the 'micromamba' executable in PATH, project data/bin, WinGet, or standard app dirs."""
        which_m = shutil.which("micromamba") or shutil.which("micromamba.exe")
        if which_m:
            return which_m

        # 1. Check project-local data/bin directory (self-contained with repo)
        data_bin = Path(config.DATA_PATH) / "bin"
        local_project_exe = data_bin / ("micromamba.exe" if sys.platform == "win32" else "micromamba")
        if local_project_exe.is_file():
            return str(local_project_exe)

        # 2. Check WinGet package directories (Windows 10/11)
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        winget_dir = local_app_data / "Microsoft" / "WinGet" / "Packages"
        if winget_dir.exists():
            for p in winget_dir.rglob("micromamba.exe"):
                if p.is_file():
                    return str(p)

        windows_apps = local_app_data / "Microsoft" / "WindowsApps" / "micromamba.exe"
        if windows_apps.is_file():
            return str(windows_apps)

        # 3. Check configured MFA directory
        base_dir = getattr(
            config,
            "DEFAULT_MFA_DIR",
            Path(getattr(config, "DATA_PATH", "data")) / "mfa",
        )
        exe_name = "micromamba.exe" if sys.platform == "win32" else "micromamba"
        local_exe = Path(base_dir) / "bin" / exe_name
        if local_exe.is_file():
            return str(local_exe)

        # 4. Check user home directories (~/.local/bin, ~/bin, ~/micromamba)
        home = Path.home()
        for cand in [
            home / ".local" / "bin" / exe_name,
            home / "bin" / exe_name,
            home / "micromamba" / exe_name,
            Path(os.environ.get("APPDATA", "")) / "mamba" / exe_name,
            local_app_data / "micromamba" / exe_name,
        ]:
            if cand.is_file():
                return str(cand)

        return None

    @classmethod
    def bootstrap_micromamba(cls) -> Optional[str]:
        """Downloads official standalone micromamba (~4.5MB compressed archive) and unpacks the binary.

        Requires ZERO external dependencies; uses Python's built-in urllib and tarfile.
        """
        import io
        import tarfile
        import platform
        import urllib.request

        # Determine target executable location in project data/bin
        target_dir = Path(config.DATA_PATH) / "bin"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            target_dir = Path.home() / ".local" / "bin"
            target_dir.mkdir(parents=True, exist_ok=True)

        exe_name = "micromamba.exe" if sys.platform == "win32" else "micromamba"
        target_exe = target_dir / exe_name

        if target_exe.is_file():
            return str(target_exe)

        # Detect operating system architecture for official micro.mamba.pm API
        mach = platform.machine().lower()
        if sys.platform == "win32":
            arch_tag = "win-64"
        elif sys.platform == "darwin":
            arch_tag = "osx-arm64" if "arm" in mach else "osx-64"
        else:
            arch_tag = "linux-aarch64" if ("arm" in mach or "aarch64" in mach) else "linux-64"

        url = f"https://micro.mamba.pm/api/micromamba/{arch_tag}/latest"
        print(f"[*] Downloading standalone Micromamba binary (~4.5MB) from {url}...", flush=True)

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (QuranReciteToText/1.0; Automator)"},
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                archive_bytes = resp.read()

            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:bz2") as tf:
                members = tf.getmembers()
                match = [m for m in members if m.name.endswith(exe_name)]
                if not match:
                    raise RuntimeError(f"Could not find '{exe_name}' inside micromamba archive.")
                extracted = tf.extractfile(match[0])
                if extracted is None:
                    raise RuntimeError(f"Failed to read '{match[0].name}' from archive.")
                with open(target_exe, "wb") as f_out:
                    f_out.write(extracted.read())

            if sys.platform != "win32":
                target_exe.chmod(0o755)

            print(f"[+] Micromamba standalone binary ready at: {target_exe}", flush=True)
            return str(target_exe)
        except Exception as e:
            logger.error(f"Failed to auto-download micromamba: {e}")
            print(f"[!] Failed to auto-download micromamba: {e}")
            return None

    @classmethod
    def find_mfa_executable(cls) -> Optional[str]:
        """Locates the 'mfa' executable in PATH, custom env vars, or standard Conda/Micromamba envs."""
        # 1. Check custom environment variable
        custom = os.environ.get("MFA_PATH") or os.environ.get("MFA_EXECUTABLE")
        if custom and os.path.isfile(custom):
            return custom

        # 2. Check current system PATH
        which_mfa = shutil.which("mfa") or shutil.which("mfa.exe")
        if which_mfa:
            return which_mfa

        # 3. Check custom or default MAMBA_ROOT_PREFIX
        candidates: List[Path] = []
        root_prefix = os.environ.get("MAMBA_ROOT_PREFIX")
        if root_prefix:
            rp = Path(root_prefix)
            candidates.extend([
                rp / "envs" / "aligner" / "Scripts" / "mfa.exe",
                rp / "envs" / "aligner" / "bin" / "mfa",
                rp / "envs" / "aligner" / "mfa.exe",
            ])

        # 4. Check standard Conda / Micromamba / Miniforge environments
        home = Path.home()
        appdata = Path(os.environ.get("APPDATA", ""))
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        programdata = Path(os.environ.get("PROGRAMDATA", ""))

        candidates.extend([
            # Micromamba default Windows prefix (%APPDATA%\mamba\envs\aligner)
            appdata / "mamba" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            appdata / "mamba" / "envs" / "aligner" / "bin" / "mfa",
            appdata / "micromamba" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            localappdata / "mamba" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            localappdata / "micromamba" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            home / "micromamba" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            home / "micromamba" / "envs" / "aligner" / "bin" / "mfa",
            home / "mamba" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            home / "mamba" / "envs" / "aligner" / "bin" / "mfa",
            home / ".local" / "share" / "mamba" / "envs" / "aligner" / "bin" / "mfa",
            home / "miniforge3" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            home / "miniforge3" / "envs" / "aligner" / "bin" / "mfa",
            home / "miniconda3" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            home / "miniconda3" / "envs" / "aligner" / "bin" / "mfa",
            home / "anaconda3" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            home / ".conda" / "envs" / "aligner" / "Scripts" / "mfa.exe",
            home / ".conda" / "envs" / "aligner" / "bin" / "mfa",
            programdata / "micromamba" / "envs" / "aligner" / "Scripts" / "mfa.exe",
        ])
        for c in candidates:
            if c.is_file():
                return str(c)
        return None

    @classmethod
    def is_mfa_installed(cls) -> bool:
        """Checks if the `mfa` executable or micromamba aligner environment is found and functional."""
        if cls.find_mfa_executable() is not None:
            return True

        # Secondary check: verify if micromamba can run 'mfa' in aligner environment
        mamba = cls.find_micromamba_executable()
        if mamba:
            try:
                env_vars = os.environ.copy()
                if "MAMBA_ROOT_PREFIX" not in env_vars:
                    default_root = (
                        os.path.join(os.environ.get("APPDATA", str(Path.home())), "mamba")
                        if sys.platform == "win32"
                        else os.path.expanduser("~/.local/share/mamba")
                    )
                    env_vars["MAMBA_ROOT_PREFIX"] = default_root

                res = subprocess.run(
                    [mamba, "run", "-n", "aligner", "mfa", "version"],
                    capture_output=True,
                    text=True,
                    env=env_vars,
                    timeout=5,
                )
                if res.returncode == 0:
                    return True
            except Exception:
                pass

        return False

    @classmethod
    def ensure_mfa_installed(cls, auto_install: bool = True) -> bool:
        """Verifies MFA is installed, or automatically bootstraps and configures it if needed.

        Uses the exact minimal CPU-only specification:
          kaldi=*=cpu*  blas=*=openblas
        Downloading only ~300MB total instead of the bloated 2GB CUDA/GPU packages.
        """
        if cls.is_mfa_installed():
            return True

        if not auto_install:
            return False

        print("\n" + "=" * 70)
        print("[*] Montreal Forced Aligner ('mfa') environment not found.")
        print("[*] Automatically configuring lightweight CPU-only environment (~300MB)...")
        print("    (One-time setup: Kaldi CPU + OpenBLAS + MFA. Zero CUDA/GPU bloat).")
        print("    (All future runs will start instantly with zero download).")
        print("=" * 70 + "\n", flush=True)

        mamba_exe = cls.find_micromamba_executable()
        conda_exe = shutil.which("conda") or shutil.which("mamba")

        if not mamba_exe and not conda_exe:
            mamba_exe = cls.bootstrap_micromamba()

        env_vars = os.environ.copy()
        if "MAMBA_ROOT_PREFIX" not in env_vars:
            if sys.platform == "win32":
                default_root = os.path.join(os.environ.get("APPDATA", str(Path.home())), "mamba")
            else:
                default_root = os.path.expanduser("~/.local/share/mamba")
            env_vars["MAMBA_ROOT_PREFIX"] = default_root

        installer_cmd: List[str] = []
        if mamba_exe:
            installer_cmd = [
                mamba_exe, "create", "-n", "aligner",
                "-c", "conda-forge",
                "montreal-forced-aligner",
                "kaldi=*=cpu*",
                "blas=*=openblas",
                "-y",
            ]
        elif conda_exe:
            installer_cmd = [
                conda_exe, "create", "-n", "aligner",
                "-c", "conda-forge",
                "montreal-forced-aligner",
                "kaldi=*=cpu*",
                "blas=*=openblas",
                "-y",
            ]

        if not installer_cmd:
            print("[!] Could not initialize a package installer.")
            return False

        print(f"[*] Executing automated environment setup: {' '.join(installer_cmd[:6])}...", flush=True)
        try:
            process = subprocess.Popen(
                installer_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env_vars,
            )
            if process.stdout:
                for line in process.stdout:
                    clean_line = line.strip()
                    if clean_line and any(
                        k in clean_line
                        for k in (
                            "Downloading",
                            "Extracting",
                            "Linking",
                            "Transaction",
                            "Done",
                            "Package",
                            "Install:",
                            "critical",
                            "error",
                            "warning",
                        )
                    ):
                        print(f"    {clean_line}", flush=True)
            process.wait()
            if process.returncode != 0:
                print(f"[!] Automated MFA setup exited with code {process.returncode}.")
                return False

            print("\n[+] Montreal Forced Aligner environment configured successfully!\n", flush=True)
            return cls.is_mfa_installed()
        except KeyboardInterrupt:
            print("\n[!] Setup interrupted by user. Continuing pipeline without MFA.")
            return False
        except Exception as e:
            print(f"[!] Error during automated MFA setup: {e}")
            return False

    def _get_rules(self) -> Dict[Tuple[int, int], List[Dict[str, Any]]]:
        if self._rule_cache is None:
            self._rule_cache = load_tajweed_rule_index(self.rule_index_path)
        return self._rule_cache

    @staticmethod
    def _split_into_monotonic_utterances(words: List[Any]) -> List[List[Any]]:
        """Partitions words into strictly forward-monotonic chronological utterances.

        DOES NOT rely on 'is_repetition: true'.
        Instead, detects acoustic restarts, pauses, and resets based directly on:
          1. Timestamp backward jump: w[i].start < w[i-1].start - 0.05
          2. Severe overlap / restart: w[i].start < w[i-1].end - 0.25
          3. Location index reset: e.g. location '55:1:1' following '55:1:3'
        """
        if not words:
            return []

        chunks: List[List[Any]] = []
        cur_chunk: List[Any] = []

        for w in words:
            if not cur_chunk:
                cur_chunk.append(w)
                continue

            prev_w = cur_chunk[-1]
            p_s = getattr(prev_w, "start", None) or 0.0
            p_e = getattr(prev_w, "end", None) or 0.0
            c_s = getattr(w, "start", None) or 0.0

            # Acoustic reset: current word starts before previous word started or overlaps heavily
            time_reset = (c_s < p_s - 0.05) or (c_s < p_e - 0.25)

            # Location index reset (e.g. reciter restarts Ayah from beginning)
            loc_reset = False
            prev_loc = getattr(prev_w, "location", None)
            curr_loc = getattr(w, "location", None)
            if prev_loc and curr_loc:
                try:
                    p_parts = [int(x) for x in str(prev_loc).split(":")]
                    c_parts = [int(x) for x in str(curr_loc).split(":")]
                    if c_parts <= p_parts:
                        loc_reset = True
                except Exception:
                    pass

            if time_reset or loc_reset:
                chunks.append(cur_chunk)
                cur_chunk = [w]
            else:
                cur_chunk.append(w)

        if cur_chunk:
            chunks.append(cur_chunk)

        return chunks

    def prepare_corpus(
        self,
        segments: List[Any],
        audio_pcm: np.ndarray,
        corpus_dir: str,
        sample_rate: int = 16000,
    ) -> List[Tuple[str, int, int, int, float, List[Any]]]:
        """Slices audio into strictly monotonic, linear WAV and LAB files ready for MFA.

        CRITICAL DESIGN RULE:
        Does NOT rely on 'is_repetition: true'. Every acoustic utterance (whether sub-segment,
        repetition, or pause-delimited pass) is treated as a standalone monotonic audio clip.
        This guarantees Montreal Forced Aligner never sees non-linear jumps.
        """
        os.makedirs(corpus_dir, exist_ok=True)
        ayah_clips: List[Tuple[str, int, int, int, float, List[Any]]] = []

        for seg in segments:
            surah = getattr(seg, "surah_number", 1)
            ayah = getattr(seg, "ayah", 1)
            subs = getattr(seg, "sub_segments", None)

            # Collect candidate word sequences: prefer sub_segments if present, else seg.words
            candidate_units: List[List[Any]] = []
            if subs:
                for sub in subs:
                    sub_words = getattr(sub, "words", [])
                    if sub_words:
                        candidate_units.append(sub_words)
            else:
                seg_words = getattr(seg, "words", [])
                if seg_words:
                    candidate_units.append(seg_words)

            # Split any internally non-monotonic chunks (e.g. restarts without sub_segment tags)
            linear_units: List[List[Any]] = []
            for unit_words in candidate_units:
                monotonic_chunks = self._split_into_monotonic_utterances(unit_words)
                linear_units.extend(monotonic_chunks)

            clip_idx = 1
            for chunk_words in linear_units:
                uthmani_words = [w.word for w in chunk_words if getattr(w, "word", None)]
                if not uthmani_words:
                    continue

                valid_starts = [w.start for w in chunk_words if getattr(w, "start", None) is not None]
                valid_ends = [w.end for w in chunk_words if getattr(w, "end", None) is not None]
                if not valid_starts or not valid_ends:
                    continue

                w_start = min(valid_starts)
                w_end = max(valid_ends)

                # Add 40ms safety margins clamped to total audio duration
                total_duration = len(audio_pcm) / sample_rate
                s_time = max(0.0, w_start - 0.04)
                e_time = min(total_duration, w_end + 0.04)

                if e_time <= s_time:
                    continue

                base_name = f"s{surah:03d}_a{ayah:03d}_c{clip_idx:02d}"
                clip_idx += 1

                lab_path = os.path.join(corpus_dir, f"{base_name}.lab")
                wav_path = os.path.join(corpus_dir, f"{base_name}.wav")

                # Write LAB text file containing ONLY the words actually uttered in this pass
                with open(lab_path, "w", encoding="utf-8") as f:
                    f.write(" ".join(uthmani_words) + "\n")

                # Slice and save 16kHz mono PCM audio
                s_idx = max(0, int(round(s_time * sample_rate)))
                e_idx = min(len(audio_pcm), int(round(e_time * sample_rate)))
                slice_pcm = audio_pcm[s_idx:e_idx]

                if slice_pcm.dtype in (np.float32, np.float64):
                    slice_int16 = (np.clip(slice_pcm, -1.0, 1.0) * 32767).astype(np.int16)
                else:
                    slice_int16 = slice_pcm.astype(np.int16)

                wavfile.write(wav_path, sample_rate, slice_int16)
                ayah_clips.append((base_name, surah, ayah, clip_idx - 1, s_time, chunk_words))

        return ayah_clips

    def run_alignment(
        self,
        corpus_dir: str,
        output_dir: str,
        beam: int = 10,
        retry_beam: int = 40,
        num_jobs: int = 2,
    ) -> bool:
        """Executes Montreal Forced Aligner command-line subprocess in fast single-speaker mode."""
        micromamba_exe = self.find_micromamba_executable()
        mfa_exe = self.find_mfa_executable()
        if not mfa_exe and not micromamba_exe:
            logger.error("MFA executable 'mfa' not found in PATH or standard environment locations.")
            return False

        if not os.path.exists(self.acoustic_model):
            logger.error(f"MFA acoustic model not found at: {self.acoustic_model}")
            return False

        if not os.path.exists(self.dictionary):
            logger.error(f"MFA dictionary not found at: {self.dictionary}")
            return False

        align_args = [
            "align",
            corpus_dir,
            self.dictionary,
            self.acoustic_model,
            output_dir,
            "--single_speaker",
            "--use_threading",
            "--no_textgrid_cleanup",
            "--num_jobs", str(num_jobs),
            "--beam", str(beam),
            "--retry_beam", str(retry_beam),
            "--overwrite",
            "--quiet",
        ]

        if micromamba_exe:
            cmd = [micromamba_exe, "run", "-n", "aligner", "mfa"] + align_args
        else:
            cmd = [mfa_exe] + align_args

        # Ensure environment PATH contains Kaldi/OpenFST libraries
        env_vars = os.environ.copy()
        if mfa_exe:
            exe_path = Path(mfa_exe)
            env_dir = exe_path.parent.parent if exe_path.parent.name.lower() in ("scripts", "bin") else exe_path.parent
            lib_bin = env_dir / "Library" / "bin"
            scripts_dir = env_dir / "Scripts"
            env_vars["PATH"] = f"{lib_bin};{scripts_dir};{env_dir};{env_vars.get('PATH', '')}"

        logger.info(f"Running MFA alignment: {' '.join(cmd)}")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env_vars)
            logger.info("MFA alignment completed successfully.")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"MFA execution failed with exit code {e.returncode}: {e.stderr}")
            return False

    def parse_aligned_outputs(
        self,
        output_dir: str,
        ayah_clips: List[Tuple[str, int, int, int, float, List[Any]]],
    ) -> List[MfaAyahResult]:
        """Parses output TextGrid files and applies global audio time offsets and Tajweed rules."""
        results: List[MfaAyahResult] = []
        rules = self._get_rules()

        ayah_groups: Dict[Tuple[int, int], List[MfaWord]] = {}

        for base_name, surah, ayah, clip_num, global_offset, chunk_words in ayah_clips:
            tg_path = os.path.join(output_dir, f"{base_name}.TextGrid")
            if not os.path.exists(tg_path):
                continue

            tiers = parse_praat_textgrid(tg_path)
            words_raw = tiers.get("words", [])
            phones_raw = tiers.get("phones", [])

            ayah_rules = rules.get((surah, ayah), [])
            rule_by_phone_idx = {r["i"]: r for r in ayah_rules if "i" in r}

            phone_idx = 0
            mfa_words: List[MfaWord] = []

            for w_idx, (w_s, w_e, w_text) in enumerate(words_raw):
                w_glob_s = round(w_s + global_offset, 3)
                w_glob_e = round(w_e + global_offset, 3)
                w_dur = round(w_glob_e - w_glob_s, 3)

                cur_phones: List[MfaPhone] = []
                for p_s, p_e, p_text in phones_raw:
                    if p_s >= (w_s - 0.015) and p_e <= (w_e + 0.015):
                        p_glob_s = round(p_s + global_offset, 3)
                        p_glob_e = round(p_e + global_offset, 3)
                        p_dur = round(p_glob_e - p_glob_s, 3)

                        r_info = rule_by_phone_idx.get(phone_idx)
                        r_name = r_info.get("rule") if r_info else None
                        g_len = r_info.get("golden_len") if r_info else None

                        cur_phones.append(
                            MfaPhone(
                                phone=p_text,
                                start=p_glob_s,
                                end=p_glob_e,
                                duration=p_dur,
                                rule=r_name,
                                golden_len=g_len,
                            )
                        )
                        phone_idx += 1

                m_word = MfaWord(
                    word=w_text,
                    start=w_glob_s,
                    end=w_glob_e,
                    duration=w_dur,
                    phones=cur_phones,
                )
                mfa_words.append(m_word)

                # Directly update in-memory QuranWord object for this pass
                if chunk_words and w_idx < len(chunk_words):
                    target_qword = chunk_words[w_idx]
                    target_qword.start = w_glob_s
                    target_qword.end = w_glob_e
                    target_qword.phonemes = [
                        {
                            "phoneme": p.phone,
                            "start": p.start,
                            "end": p.end,
                            **({"rule": p.rule} if p.rule else {}),
                            **({"golden_len": p.golden_len} if p.golden_len else {}),
                        }
                        for p in cur_phones
                    ]

            key = (surah, ayah)
            if key not in ayah_groups:
                ayah_groups[key] = []
            ayah_groups[key].extend(mfa_words)

        for (s, a), all_w in ayah_groups.items():
            if all_w:
                results.append(
                    MfaAyahResult(
                        surah=s,
                        ayah=a,
                        start_time=all_w[0].start,
                        end_time=all_w[-1].end,
                        words=all_w,
                    )
                )

        return results

    def align_pipeline_result(
        self,
        pipeline_result: Any,
        audio_pcm: np.ndarray,
        output_dir: str = ".",
    ) -> Optional[List[MfaAyahResult]]:
        """Main end-to-end interface to run MFA refinement on an existing PipelineResult."""
        if not self.is_mfa_installed():
            print("\n" + "=" * 70)
            print("[*] Montreal Forced Aligner ('mfa') requested via --mfa.")
            print("[*] Environment not detected. Initiating automated setup (~300MB CPU-only)...")
            print("=" * 70 + "\n", flush=True)
            success = self.ensure_mfa_installed(auto_install=True)
            if not success:
                print("\n[!] Automatic MFA setup could not be completed.")
                print("    Continuing pipeline with baseline transcription & alignment (Phases 1-4).\n", flush=True)
                return None

        segments = getattr(pipeline_result, "segments", [])
        if not segments:
            logger.warning("No matched Ayah segments available to align with MFA.")
            return None

        work_dir = os.path.join(output_dir, "mfa_workspace")
        corpus_dir = os.path.join(work_dir, "corpus")
        mfa_out_dir = os.path.join(work_dir, "aligned_textgrids")

        # Ensure a clean workspace with no leftover files from previous recitations
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir, exist_ok=True)

        print("[*] Preparing Ayah audio clips for MFA alignment...", flush=True)
        clips = self.prepare_corpus(segments, audio_pcm, corpus_dir)
        if not clips:
            logger.warning("No valid Ayah clips could be prepared for MFA.")
            return None

        print(f"[*] Running MFA on {len(clips)} Ayah clips (10ms resolution)...", flush=True)
        success = self.run_alignment(corpus_dir, mfa_out_dir)
        if not success:
            if getattr(config, "CLEANUP_MFA_WORKSPACE", True):
                shutil.rmtree(work_dir, ignore_errors=True)
            return None

        print("[*] Parsing MFA Praat TextGrids & Tajweed rules...", flush=True)
        mfa_results = self.parse_aligned_outputs(mfa_out_dir, clips)

        # Discard temporary intermediate WAV/TextGrid files once parsed into memory
        if getattr(config, "CLEANUP_MFA_WORKSPACE", True):
            shutil.rmtree(work_dir, ignore_errors=True)

        # Export canonical MFA JSON artifacts
        mfa_export = {
            "total_ayahs": len(mfa_results),
            "ayahs": [r.to_dict() for r in mfa_results],
        }

        mfa_json_path = os.path.join(output_dir, "mfa_output.json")
        with open(mfa_json_path, "w", encoding="utf-8") as f:
            json.dump(mfa_export, f, ensure_ascii=False, indent=2)

        # Also export flat phone-level timeline
        flat_phones = []
        p_idx = 1
        for a in mfa_results:
            for w in a.words:
                for p in w.phones:
                    flat_phones.append({
                        "index": p_idx,
                        "surah": a.surah,
                        "ayah": a.ayah,
                        "word": w.word,
                        **p.to_dict(),
                    })
                    p_idx += 1

        flat_json_path = os.path.join(output_dir, "mfa_aligned_phones.json")
        with open(flat_json_path, "w", encoding="utf-8") as f:
            json.dump({"total_phones": len(flat_phones), "phones": flat_phones}, f, ensure_ascii=False, indent=2)

        # Update pipeline_result in memory so output.json also receives the 10ms MFA timings
        for m_ayah in mfa_results:
            for seg in getattr(pipeline_result, "segments", []):
                if seg.surah_number == m_ayah.surah and seg.ayah == m_ayah.ayah:
                    seg.start_time = m_ayah.start_time
                    seg.end_time = m_ayah.end_time
                    for w_idx, m_w in enumerate(m_ayah.words):
                        if w_idx < len(seg.words):
                            target_word = seg.words[w_idx]
                            target_word.start = m_w.start
                            target_word.end = m_w.end
                            target_word.phonemes = [
                                {
                                    "phoneme": p.phone,
                                    "start": round(p.start, 3),
                                    "end": round(p.end, 3),
                                    **({"rule": p.rule} if p.rule else {}),
                                    **({"golden_len": p.golden_len} if p.golden_len else {}),
                                }
                                for p in m_w.phones
                            ]

        # Re-export output.json with updated MFA letter-level timings
        if hasattr(pipeline_result, "export_json"):
            pipeline_result.export_json(output_dir=output_dir)

        print(f"[+] MFA Alignment complete! Artifacts saved:")
        print(f"    - {mfa_json_path}")
        print(f"    - {flat_json_path}")
        print(f"    - {os.path.join(output_dir, 'output.json')} (synced with MFA phone timings)")

        return mfa_results
