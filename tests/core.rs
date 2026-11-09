use agentic_secret_manager::{
    Error,
    config::Config,
    engine::{Engine, extract, validate_url},
    store::{MemoryStore, Store},
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, time::Instant};

fn config(operations: Value) -> Config {
    serde_json::from_value(json!({"namespace":"test", "secrets":{"token":{"description":"test credential"}}, "operations":operations})).unwrap()
}
fn engine(operations: Value, base: &std::path::Path) -> Engine {
    Engine::new(
        config(operations),
        Box::new(MemoryStore::default()),
        base.into(),
        false,
    )
    .unwrap()
}

#[test]
fn capture_deliver_preserves_value_and_hides_it_in_outcomes() {
    let dir = tempfile::tempdir().unwrap();
    let sentinel = "SYNTHETIC-only- spaces ! ü &\"";
    std::fs::write(
        dir.path().join("source.json"),
        json!({"token":sentinel}).to_string(),
    )
    .unwrap();
    let mut engine = engine(
        json!({
            "capture":{"kind":"capture","secret":"token","source":{"kind":"file","path":"source.json","json_pointer":"/token"}},
            "deliver":{"kind":"deliver","secret":"token","destination":{"kind":"file","path":"target"}}
        }),
        dir.path(),
    );
    for name in ["capture", "deliver"] {
        let result = serde_json::to_string(&engine.execute(name).unwrap()).unwrap();
        assert!(!result.contains(sentinel));
        assert!(result.contains("asm://test/token"));
    }
    assert_eq!(
        std::fs::read_to_string(dir.path().join("target")).unwrap(),
        sentinel
    );
    use std::os::unix::fs::PermissionsExt;
    assert_eq!(
        std::fs::metadata(dir.path().join("target"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    assert_eq!(
        engine.execute("capture").err(),
        Some(Error("secret_already_exists"))
    );
    assert_eq!(
        engine.execute("deliver").err(),
        Some(Error("destination_exists_or_write_failed"))
    );
    assert!(!engine.catalog().to_string().contains(sentinel));
}

#[test]
fn generate_no_overwrite_delete_and_missing_secret() {
    let dir = tempfile::tempdir().unwrap();
    let mut engine = engine(
        json!({
            "generate":{"kind":"generate","secret":"token","bytes":32},
            "deliver":{"kind":"deliver","secret":"token","destination":{"kind":"file","path":"target"}}
        }),
        dir.path(),
    );
    assert_eq!(
        engine.execute("deliver").err(),
        Some(Error("secret_not_found"))
    );
    engine.execute("generate").unwrap();
    engine.execute("deliver").unwrap();
    assert_eq!(std::fs::read(dir.path().join("target")).unwrap().len(), 43);
    assert_eq!(
        engine.execute("generate").err(),
        Some(Error("secret_already_exists"))
    );
    engine.delete("token").unwrap();
    assert_eq!(engine.delete("token"), Err(Error("secret_not_found")));
    engine.execute("generate").unwrap();
}

#[test]
fn environment_metadata_preserves_legacy_storage_and_reference() {
    let dir = tempfile::tempdir().unwrap();
    let mut engine = engine(
        json!({
            "generate":{"kind":"generate","secret":"token","bytes":32},
            "deliver":{"kind":"deliver","secret":"token","destination":{"kind":"file","path":"target"}}
        }),
        dir.path(),
    );
    let legacy = serde_json::to_value(engine.execute("generate").unwrap()).unwrap();
    assert_eq!(legacy.get("environment"), Some(&Value::Null));
    assert_eq!(
        engine.catalog()["secrets"][0].get("environment"),
        Some(&Value::Null)
    );

    engine.config.secrets.get_mut("token").unwrap().environment = Some("production".into());
    let outcome = serde_json::to_value(engine.execute("deliver").unwrap()).unwrap();
    assert_eq!(outcome["environment"], "production");
    assert_eq!(outcome["secret_ref"], legacy["secret_ref"]);
    assert_eq!(std::fs::read(dir.path().join("target")).unwrap().len(), 43);
    let catalog = engine.catalog();
    assert_eq!(catalog["secrets"][0]["environment"], "production");
    for operation in catalog["operations"].as_array().unwrap() {
        assert_eq!(operation["environment"], "production");
    }
}

#[test]
fn environment_metadata_validates_without_guessing_or_echoing() {
    for label in [
        json!(null),
        json!("development"),
        json!("staging"),
        json!("production"),
        json!("preview/pr-42"),
    ] {
        let parsed: Config = serde_json::from_value(json!({"namespace":"prod-name-is-not-default", "secrets":{"token":{"description":"test", "environment":label}}, "operations":{}})).unwrap();
        parsed.validate().unwrap();
        assert_eq!(
            serde_json::to_value(&parsed.secrets["token"]).unwrap()["environment"],
            label
        );
    }
    for label in ["", " production", "secret\nvalue", &"a".repeat(129)] {
        let mut config = config(json!({}));
        config.secrets.get_mut("token").unwrap().environment = Some(label.into());
        assert_eq!(config.validate(), Err(Error("invalid_secret_environment")));
    }
    let invalid_type = json!({"namespace":"test", "secrets":{"token":{"description":"test", "environment":42}}, "operations":{}});
    assert!(serde_json::from_value::<Config>(invalid_type).is_err());
}

#[test]
fn validation_fails_closed() {
    assert!(validate_url("http://example.com", true).is_err());
    assert!(validate_url("http://127.0.0.1:1234", false).is_err());
    assert!(validate_url("http://127.0.0.1:1234", true).is_ok());
    assert!(validate_url("https://user:password@example.com", false).is_err());
    assert!(validate_url("file:///tmp/token", false).is_err());
    assert!(
        config(json!({"weak":{"kind":"generate","secret":"token","bytes":1}}))
            .validate()
            .is_err()
    );
    assert!(
        config(json!({"missing":{"kind":"generate","secret":"other","bytes":32}}))
            .validate()
            .is_err()
    );
    assert!(extract(b"{\"secret\":\"SENSITIVE\"}", Some("/missing")).is_err());
    assert!(extract(b"", None).is_err());
    assert_eq!(
        extract(b" with spaces \r\n", None).unwrap().as_str(),
        " with spaces "
    );
    assert_eq!(
        extract(b"{\"a/b\":\"token\"}", Some("/a~1b"))
            .unwrap()
            .as_str(),
        "token"
    );
}

#[test]
fn command_failure_output_and_timeout_never_escape() {
    use agentic_secret_manager::{config::CommandSpec, process};
    let mut spec = CommandSpec {
        program: "/bin/sh".into(),
        args: vec![
            "-c".into(),
            "printf SECRET; printf SECRET >&2; exit 3".into(),
        ],
        cwd: "/tmp".into(),
        timeout_seconds: 1,
        secret_env: BTreeMap::new(),
    };
    assert_eq!(
        process::run(&spec, &BTreeMap::new()).err(),
        Some(Error("command_failed"))
    );
    spec.args[1] = "sleep 10 & wait".into();
    let start = Instant::now();
    assert_eq!(
        process::run(&spec, &BTreeMap::new()).err(),
        Some(Error("command_timeout"))
    );
    assert!(start.elapsed().as_secs() < 3);
    spec.args[1] = "head -c 1048577 /dev/zero".into();
    // Exercise the size limit independently of timer granularity on CI hosts.
    spec.timeout_seconds = 10;
    assert_eq!(
        process::run(&spec, &BTreeMap::new()).err(),
        Some(Error("capture_too_large"))
    );
}

#[test]
fn memory_store_requires_explicit_replace() {
    let mut store = MemoryStore::default();
    store.put("x", "first", false).unwrap();
    assert_eq!(
        store.put("x", "second", false),
        Err(Error("secret_already_exists"))
    );
    assert_eq!(store.get("x").unwrap().as_str(), "first");
    store.put("x", "second", true).unwrap();
    assert_eq!(store.get("x").unwrap().as_str(), "second");
}

#[test]
fn fifo_sources_and_configs_fail_without_waiting_for_writer() {
    let directory = tempfile::tempdir().unwrap();
    let fifo = directory.path().join("fifo");
    let name = std::ffi::CString::new(fifo.as_os_str().as_encoded_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
    for config_is_fifo in [false, true] {
        let config_path = directory.path().join("config.json");
        std::fs::write(&config_path, json!({"namespace":"test", "secrets":{"token":{"description":"test"}}, "operations":{"capture":{"kind":"capture","secret":"token","source":{"kind":"file","path":"fifo"}}}}).to_string()).unwrap();
        let mut child = std::process::Command::new(env!("CARGO_BIN_EXE_asm"))
            .args([
                "--config",
                if config_is_fifo {
                    fifo.to_str().unwrap()
                } else {
                    config_path.to_str().unwrap()
                },
                "--ephemeral",
                "execute",
                "capture",
            ])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .unwrap();
        let start = Instant::now();
        let completed = loop {
            if let Some(status) = child.try_wait().unwrap() {
                break Some(status);
            }
            if start.elapsed().as_secs() >= 2 {
                break None;
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        };
        if completed.is_none() {
            child.kill().unwrap();
            child.wait().unwrap();
        }
        assert!(
            completed.is_some_and(|s| !s.success()),
            "FIFO input hung or was accepted"
        );
    }
}
