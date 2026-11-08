use crate::{Error, MAX_CAPTURE, Result, config::CommandSpec};
use std::{
    collections::BTreeMap,
    io::Read,
    os::{fd::AsRawFd, unix::process::CommandExt},
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};
use zeroize::Zeroizing;

struct ChildGuard(Child);
impl Drop for ChildGuard {
    fn drop(&mut self) {
        // The child owns its process group; never signal the caller's group.
        unsafe {
            libc::kill(-(self.0.id() as i32), libc::SIGKILL);
        }
        let _ = self.0.wait();
    }
}

pub fn run(
    spec: &CommandSpec,
    env: &BTreeMap<String, Zeroizing<String>>,
) -> Result<Zeroizing<Vec<u8>>> {
    if !spec.program.is_absolute()
        || !spec.cwd.is_absolute()
        || !(1..=60).contains(&spec.timeout_seconds)
    {
        return Err(Error("invalid_command_config"));
    }
    if env.keys().any(|k| k.is_empty() || k.contains(['=', '\0'])) {
        return Err(Error("invalid_environment_name"));
    }
    let mut command = Command::new(&spec.program);
    command
        .args(&spec.args)
        .current_dir(&spec.cwd)
        .env_clear()
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    for key in ["PATH", "HOME", "TMPDIR", "LANG", "SYSTEMROOT"] {
        if let Some(value) = std::env::var_os(key) {
            command.env(key, value);
        }
    }
    for (key, value) in env {
        command.env(key, value.as_str());
    }
    unsafe {
        command.pre_exec(|| {
            if libc::setsid() == -1 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let mut child = ChildGuard(command.spawn().map_err(|_| Error("command_start_failed"))?);
    let mut stdout = child.0.stdout.take().ok_or(Error("command_io_failed"))?;
    let fd = stdout.as_raw_fd();
    unsafe {
        let flags = libc::fcntl(fd, libc::F_GETFL);
        if flags == -1 || libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) == -1 {
            return Err(Error("command_io_failed"));
        }
    }
    let start = Instant::now();
    let mut output = Zeroizing::new(Vec::new());
    let mut eof = false;
    loop {
        let mut chunk = Zeroizing::new([0u8; 8192]);
        match stdout.read(&mut *chunk) {
            Ok(0) => eof = true,
            Ok(n) => {
                if output.len() + n > MAX_CAPTURE {
                    return Err(Error("capture_too_large"));
                }
                output.extend_from_slice(&chunk[..n]);
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => (),
            Err(_) => return Err(Error("command_io_failed")),
        }
        if let Some(status) = child
            .0
            .try_wait()
            .map_err(|_| Error("command_wait_failed"))?
        {
            if !status.success() {
                return Err(Error("command_failed"));
            }
            if eof {
                return Ok(output);
            }
        }
        if start.elapsed() >= Duration::from_secs(spec.timeout_seconds) {
            return Err(Error("command_timeout"));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}
