pub mod browser;
pub mod config;
pub mod engine;
pub mod mcp;
pub mod process;
pub mod store;

use std::fmt;

/// Only static codes cross the agent boundary. Never wrap upstream error text.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Error(pub &'static str);
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}
impl std::error::Error for Error {}
pub type Result<T> = std::result::Result<T, Error>;
pub const MAX_SECRET: usize = 16 * 1024;
pub const MAX_CAPTURE: usize = 1024 * 1024;

pub fn open_regular(path: &std::path::Path) -> Result<std::fs::File> {
    use std::os::unix::fs::OpenOptionsExt;
    // Nonblocking open prevents a FIFO from hanging before metadata inspection.
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY)
        .open(path)
        .map_err(|_| Error("source_read_failed"))?;
    if !file
        .metadata()
        .map_err(|_| Error("source_read_failed"))?
        .is_file()
    {
        return Err(Error("source_not_regular_file"));
    }
    Ok(file)
}

pub fn validate_secret(value: String) -> Result<zeroize::Zeroizing<String>> {
    let value = zeroize::Zeroizing::new(value);
    if value.is_empty() || value.len() > MAX_SECRET || value.contains('\0') {
        return Err(Error("invalid_secret_value"));
    }
    Ok(value)
}
