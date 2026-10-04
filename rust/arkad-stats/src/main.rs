//! arkad-stats: streams JSON system stats (RAM/CPU) on stdout, one line per
//! second. Python spawns this once and drains lines non-blocking; the daemon
//! owns the CPU jiffy delta so every emitted sample is already a true %.
//!
//! Output: {"ram_used_gb":6.4,"ram_total_gb":15.0,"cpu_pct":3.2}

use std::io::{self, BufWriter, Write};
use std::fs;
use std::thread;
use std::time::Duration;

fn ram_gb() -> (f64, f64) {
    let mut total = 0f64;
    let mut avail = 0f64;
    if let Ok(s) = fs::read_to_string("/proc/meminfo") {
        for line in s.lines() {
            if let Some(rest) = line.strip_prefix("MemTotal:") {
                total = rest.trim().split_whitespace().next().and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / 1024.0 / 1024.0;
            } else if let Some(rest) = line.strip_prefix("MemAvailable:") {
                avail = rest.trim().split_whitespace().next().and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / 1024.0 / 1024.0;
            }
        }
    }
    (total - avail, total)
}

fn cpu_jiffies() -> (u64, u64) {
    // idle, total
    let s = fs::read_to_string("/proc/stat").unwrap_or_default();
    let first = s.lines().next().unwrap_or("");
    let nums: Vec<u64> = first
        .split_whitespace()
        .skip(1)
        .filter_map(|x| x.parse().ok())
        .collect();
    if nums.len() < 4 {
        return (0, 0);
    }
    let idle = nums[3] + nums.get(4).copied().unwrap_or(0);
    let total: u64 = nums.iter().sum();
    (idle, total)
}

fn main() {
    let mut prev = cpu_jiffies();
    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());
    loop {
        thread::sleep(Duration::from_secs(1));
        let now = cpu_jiffies();
        let dt = now.1.saturating_sub(prev.1);
        let di = now.0.saturating_sub(prev.0);
        prev = now;
        let cpu = if dt > 0 {
            ((1.0 - di as f64 / dt as f64) * 100.0).clamp(0.0, 100.0)
        } else {
            0.0
        };
        let (used, total) = ram_gb();
        let _ = writeln!(
            out,
            "{{\"ram_used_gb\":{:.1},\"ram_total_gb\":{:.1},\"cpu_pct\":{:.1}}}",
            used, total, cpu
        );
        let _ = out.flush();
    }
}
