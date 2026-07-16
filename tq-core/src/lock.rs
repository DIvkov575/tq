use std::fs::{File, OpenOptions};
use std::path::{Path, PathBuf};

use fs2::FileExt;

use crate::error::{Error, Result};

/// Holds an exclusive flock on a `.lock` sidecar file for the duration of
/// its lifetime. Lock file is separate from the data file so callers can
/// hold the lock across a read-modify-write cycle without truncating the
/// data file early.
pub struct FileLock {
    _file: File,
}

impl FileLock {
    pub fn acquire(data_path: &Path) -> Result<Self> {
        let lock_path: PathBuf = data_path.with_extension("lock");
        if let Some(parent) = lock_path.parent() {
            std::fs::create_dir_all(parent).map_err(|source| Error::Io {
                path: parent.to_path_buf(),
                source,
            })?;
        }
        let file = OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|source| Error::Io {
                path: lock_path.clone(),
                source,
            })?;
        file.lock_exclusive().map_err(|source| Error::Io {
            path: lock_path,
            source,
        })?;
        Ok(FileLock { _file: file })
    }
}

impl Drop for FileLock {
    fn drop(&mut self) {
        let _ = self._file.unlock();
    }
}
