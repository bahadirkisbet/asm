use crate::{Error, Result};
use std::collections::BTreeMap;
use zeroize::Zeroizing;

pub trait Store: Send {
    fn get(&self, name: &str) -> Result<Zeroizing<String>>;
    fn put(&mut self, name: &str, value: &str, replace: bool) -> Result<()>;
    fn delete(&mut self, name: &str) -> Result<()>;
}

#[derive(Default)]
pub struct MemoryStore(BTreeMap<String, Zeroizing<String>>);
impl Store for MemoryStore {
    fn get(&self, name: &str) -> Result<Zeroizing<String>> {
        self.0.get(name).cloned().ok_or(Error("secret_not_found"))
    }
    fn put(&mut self, name: &str, value: &str, replace: bool) -> Result<()> {
        if !replace && self.0.contains_key(name) {
            return Err(Error("secret_already_exists"));
        }
        self.0
            .insert(name.to_owned(), Zeroizing::new(value.to_owned()));
        Ok(())
    }
    fn delete(&mut self, name: &str) -> Result<()> {
        self.0.remove(name).ok_or(Error("secret_not_found"))?;
        Ok(())
    }
}

pub struct OsStore {
    service: String,
}
impl OsStore {
    pub fn new(namespace: &str) -> Self {
        Self {
            service: format!("asm/{namespace}"),
        }
    }
    fn entry(&self, name: &str) -> Result<keyring::Entry> {
        keyring::Entry::new(&self.service, name).map_err(|_| Error("credential_store_unavailable"))
    }
}
impl Store for OsStore {
    fn get(&self, name: &str) -> Result<Zeroizing<String>> {
        let value = self.entry(name)?.get_password().map_err(|e| match e {
            keyring::Error::NoEntry => Error("secret_not_found"),
            _ => Error("credential_read_failed"),
        })?;
        crate::validate_secret(value)
    }
    fn put(&mut self, name: &str, value: &str, replace: bool) -> Result<()> {
        let entry = self.entry(name)?;
        if !replace {
            match self.get(name) {
                Ok(_) => return Err(Error("secret_already_exists")),
                Err(Error("secret_not_found")) => (),
                Err(e) => return Err(e),
            }
        }
        entry
            .set_password(value)
            .map_err(|_| Error("credential_write_failed"))
    }
    fn delete(&mut self, name: &str) -> Result<()> {
        self.entry(name)?.delete_credential().map_err(|e| match e {
            keyring::Error::NoEntry => Error("secret_not_found"),
            _ => Error("credential_delete_failed"),
        })
    }
}

/// Serialize ASM read/check/write across CLI and MCP processes for this user.
pub fn lock() -> Result<std::fs::File> {
    use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
    let home = std::env::var_os("HOME").ok_or(Error("home_missing"))?;
    let directory = std::path::PathBuf::from(home).join(".local/state/asm");
    std::fs::create_dir_all(&directory).map_err(|_| Error("lock_failed"))?;
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))
        .map_err(|_| Error("lock_failed"))?;
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(directory.join("store.lock"))
        .map_err(|_| Error("lock_failed"))?;
    fs2::FileExt::try_lock_exclusive(&file).map_err(|_| Error("store_busy_retry"))?;
    Ok(file)
}
