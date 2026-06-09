import json
import threading

from autotoken.services.task_runtime import (
    TASK_GROUP_DEFAULT,
    TASK_GROUP_GOPAY,
    TASK_GROUP_OAUTH,
    TASK_GROUP_REGISTER,
    acquire_task_run_slot,
    acquire_task_start_slot,
    activate_current_task_index,
    append_live_task_progress,
    append_task_progress_event,
    apply_gopay_runtime_control_public_updates,
    bind_task_thread_context,
    busy_task_detail,
    cancel_orphaned_task_snapshots,
    clear_current_task_index,
    clear_task_cancel_hooks,
    clear_task_runtime_state,
    clear_task_thread_context,
    create_task_record,
    current_task_id_for_group,
    drain_gopay_pending_account_emails,
    ensure_task_cancel_event,
    execute_task_callable,
    find_control_task,
    gopay_runtime_control_progress_event,
    gopay_runtime_control_update_message,
    gopay_skip_current_error,
    gopay_skip_current_progress_event,
    gopay_skip_current_response,
    init_gopay_runtime_control,
    interrupted_task_snapshot,
    launch_task_thread,
    load_task_snapshots,
    mark_task_cancel_requested,
    mark_task_completed,
    mark_task_failed,
    mark_task_finished,
    mark_task_prestart_cancelled,
    mark_task_run_finished,
    mark_task_run_prestart_cancelled,
    mark_task_running,
    mark_task_skip_current_requested,
    merged_task_snapshots,
    normalize_task_group,
    persist_task_snapshot,
    prepare_task_start,
    prune_task_history,
    register_task_cancel_hook,
    release_task_run_slot,
    release_task_start_slot,
    rollback_task_start,
    run_task_cancel_hooks,
    running_task_for_group,
    runtime_control,
    task_cancel_requested_progress_event,
    task_cancel_requested_response,
    task_control_status_error,
    task_detail_snapshot,
    task_group_lock,
    update_gopay_runtime_control,
)


def test_normalize_task_group_prefers_explicit_group():
    assert normalize_task_group("custom", "register") == "custom"


def test_normalize_task_group_maps_known_commands():
    assert normalize_task_group(None, "register") == TASK_GROUP_REGISTER
    assert normalize_task_group(None, "gopay-bind") == TASK_GROUP_GOPAY
    assert normalize_task_group(None, "login:user@example.com") == TASK_GROUP_OAUTH


def test_normalize_task_group_falls_back_to_default():
    assert normalize_task_group(None, "unknown") == TASK_GROUP_DEFAULT
    assert normalize_task_group(None, "") == TASK_GROUP_DEFAULT


def test_task_group_lock_reuses_existing_group_lock():
    locks = {}
    first = task_group_lock(locks, TASK_GROUP_REGISTER, lock_factory=threading.Lock)
    second = task_group_lock(locks, TASK_GROUP_REGISTER, lock_factory=threading.Lock)

    assert first is second
    assert set(locks) == {TASK_GROUP_REGISTER}


def test_acquire_task_start_slot_acquires_exclusive_group_lock():
    locks = {}

    slot = acquire_task_start_slot(locks, TASK_GROUP_REGISTER, exclusive=True, lock_factory=threading.Lock)
    try:
        assert slot.task_group == TASK_GROUP_REGISTER
        assert slot.acquired is True
        assert slot.conflict is False
        assert locks[TASK_GROUP_REGISTER] is slot.lock
        assert slot.lock.acquire(blocking=False) is False
    finally:
        release_task_start_slot(slot)

    assert locks[TASK_GROUP_REGISTER].acquire(blocking=False) is True
    locks[TASK_GROUP_REGISTER].release()


def test_acquire_task_start_slot_reports_exclusive_conflict_without_unlocking_existing_owner():
    locks = {}
    owner = acquire_task_start_slot(locks, TASK_GROUP_REGISTER, exclusive=True, lock_factory=threading.Lock)
    conflict = acquire_task_start_slot(locks, TASK_GROUP_REGISTER, exclusive=True, lock_factory=threading.Lock)

    assert conflict.acquired is False
    assert conflict.conflict is True
    assert conflict.lock is owner.lock
    release_task_start_slot(conflict)
    assert owner.lock.acquire(blocking=False) is False
    release_task_start_slot(owner)


def test_acquire_task_start_slot_skips_lock_for_nonexclusive_task():
    locks = {}

    slot = acquire_task_start_slot(locks, TASK_GROUP_REGISTER, exclusive=False, lock_factory=threading.Lock)

    assert slot.task_group == TASK_GROUP_REGISTER
    assert slot.lock is None
    assert slot.acquired is False
    assert slot.conflict is False
    assert locks == {}


def test_acquire_task_run_slot_consumes_preacquired_marker_and_releases_lock():
    lock = threading.Lock()
    assert lock.acquire(blocking=False) is True
    task = {"_group_lock_preacquired": True}

    slot = acquire_task_run_slot(task, TASK_GROUP_REGISTER, lock)

    assert slot.task_group == TASK_GROUP_REGISTER
    assert slot.preacquired is True
    assert "_group_lock_preacquired" not in task
    assert lock.acquire(blocking=False) is False
    release_task_run_slot(slot)
    assert lock.acquire(blocking=False) is True
    lock.release()


def test_acquire_task_run_slot_acquires_missing_runtime_lock():
    lock = threading.Lock()
    task = {}

    slot = acquire_task_run_slot(task, TASK_GROUP_REGISTER, lock)

    assert slot.preacquired is False
    assert lock.acquire(blocking=False) is False
    release_task_run_slot(slot)
    assert lock.acquire(blocking=False) is True
    lock.release()


def test_rollback_task_start_releases_slot_and_clears_runtime_state():
    locks = {}
    start_slot = acquire_task_start_slot(locks, TASK_GROUP_REGISTER, exclusive=True, lock_factory=threading.Lock)
    tasks = {"task-1": {"task_id": "task-1"}}
    skip_signals = {"task-1": object()}
    cancel_signals = {"task-1": object()}
    cancel_hooks = {"task-1": [lambda: None]}
    controls = {"task-1": {"value": 1}}
    hooks_lock = threading.RLock()
    controls_lock = threading.RLock()

    removed = rollback_task_start(
        tasks,
        "task-1",
        start_slot,
        skip_signals=skip_signals,
        cancel_signals=cancel_signals,
        cancel_hooks=cancel_hooks,
        cancel_hooks_lock=hooks_lock,
        controls=controls,
        controls_lock=controls_lock,
    )

    assert removed == {"task_id": "task-1"}
    assert tasks == {}
    assert skip_signals == {}
    assert cancel_signals == {}
    assert cancel_hooks == {}
    assert controls == {}
    assert locks[TASK_GROUP_REGISTER].acquire(blocking=False) is True
    locks[TASK_GROUP_REGISTER].release()


def test_launch_task_thread_starts_thread_with_task_runner_args():
    calls = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            calls.append(("created", kwargs))

        def start(self):
            calls.append(("started", self.kwargs))

    def fake_target():
        return None

    def fake_func():
        return None

    thread = launch_task_thread(
        thread_factory=FakeThread,
        target=fake_target,
        task_id="task-1",
        func=fake_func,
        pass_task_id=True,
        args=("extra",),
        kwargs={"value": 1},
    )

    assert isinstance(thread, FakeThread)
    assert calls[0][0] == "created"
    assert calls[0][1]["target"] is fake_target
    assert calls[0][1]["args"] == ("task-1", fake_func, True, "extra")
    assert calls[0][1]["kwargs"] == {"value": 1}
    assert calls[0][1]["daemon"] is True
    assert calls[1][0] == "started"


def test_launch_task_thread_runs_error_callback_and_reraises_start_failure():
    calls = []

    class BrokenThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("cannot start")

    try:
        launch_task_thread(
            thread_factory=BrokenThread,
            target=lambda: None,
            task_id="task-1",
            func=lambda: None,
            on_start_error=lambda: calls.append("rollback"),
        )
    except RuntimeError as exc:
        assert str(exc) == "cannot start"
    else:
        raise AssertionError("expected thread start failure")

    assert calls == ["rollback"]


def test_bind_task_thread_context_sets_attrs_and_cancel_event():
    context = type("Context", (), {})()
    cancel_event = threading.Event()
    calls = []

    bind_task_thread_context(
        context,
        task_id="task-1",
        task_group=TASK_GROUP_REGISTER,
        cancel_event=cancel_event,
        set_cancel_event=lambda event: calls.append(event),
    )

    assert context.task_id == "task-1"
    assert context.task_group == TASK_GROUP_REGISTER
    assert context.cancel_event is cancel_event
    assert calls == [cancel_event]


def test_clear_task_thread_context_clears_attrs_and_cancel_event():
    context = type("Context", (), {})()
    context.task_id = "task-1"
    context.task_group = TASK_GROUP_REGISTER
    context.cancel_event = threading.Event()
    context.worker_label = "worker-1"
    calls = []

    clear_task_thread_context(
        context,
        clear_cancel_event=lambda: calls.append("cleared"),
        extra_attrs=("worker_label", "missing_attr"),
    )

    assert calls == ["cleared"]
    assert not hasattr(context, "task_id")
    assert not hasattr(context, "task_group")
    assert not hasattr(context, "cancel_event")
    assert not hasattr(context, "worker_label")


def test_running_task_for_group_resolves_current_group_task():
    tasks = {"task-1": {"task_id": "task-1"}}
    current_task_ids = {TASK_GROUP_REGISTER: "task-1"}

    assert running_task_for_group(tasks, current_task_ids, TASK_GROUP_REGISTER) == {"task_id": "task-1"}
    assert running_task_for_group(tasks, current_task_ids, TASK_GROUP_GOPAY) == {}


def test_find_control_task_prefers_requested_task_id():
    task = {"task_id": "task-1", "status": "completed"}
    result = find_control_task({"task-1": task}, {}, task_id=" task-1 ")

    assert result.found is True
    assert result.task is task


def test_find_control_task_reports_missing_requested_task():
    result = find_control_task({}, {}, task_id="missing")

    assert result.found is False
    assert result.status_code == 404
    assert result.detail == "任务不存在"


def test_find_control_task_uses_current_task_for_requested_group():
    older = {"task_id": "older", "task_group": TASK_GROUP_GOPAY, "status": "running", "started_at": 1}
    current = {"task_id": "current", "task_group": TASK_GROUP_GOPAY, "status": "running", "started_at": 2}
    result = find_control_task(
        {"older": older, "current": current},
        {TASK_GROUP_GOPAY: "older"},
        task_group=TASK_GROUP_GOPAY,
    )

    assert result.task is older


def test_find_control_task_falls_back_to_latest_matching_running_task():
    older = {"task_id": "older", "command": "register", "task_group": TASK_GROUP_REGISTER, "status": "running", "started_at": 2}
    newest = {"task_id": "newest", "command": "register", "task_group": TASK_GROUP_REGISTER, "status": "pending", "created_at": 3}
    ignored = {"task_id": "ignored", "command": "gopay-bind", "task_group": TASK_GROUP_GOPAY, "status": "running", "started_at": 4}
    result = find_control_task(
        {"older": older, "newest": newest, "ignored": ignored},
        {},
        command="register",
    )

    assert result.task is newest


def test_find_control_task_reports_no_running_task():
    result = find_control_task({"done": {"task_id": "done", "status": "completed"}}, {}, command="register")

    assert result.found is False
    assert result.status_code == 404
    assert result.detail == "当前没有正在运行的任务"


def test_task_control_status_error_allows_running_and_pending_only():
    assert task_control_status_error({"status": "running"}, "取消") == ""
    assert task_control_status_error({"status": "pending"}, "取消") == ""
    assert task_control_status_error({"status": "completed"}, "取消") == "任务当前状态 completed 无法取消"


def test_mark_task_cancel_requested_sets_task_flag():
    task = {"task_id": "task-1", "command": "register", "task_group": TASK_GROUP_REGISTER}

    mark_task_cancel_requested(task)

    assert task["cancel_requested"] is True
    assert task_cancel_requested_progress_event() == {
        "stage": "task_cancel_requested",
        "message": "已请求立即中止任务，正在停止提交新步骤并打断当前可中断等待",
    }
    assert task_cancel_requested_response(task) == {
        "message": "已请求立即中止，正在停止提交新步骤并打断当前可中断等待",
        "task_id": "task-1",
        "command": "register",
        "task_group": TASK_GROUP_REGISTER,
    }


def test_gopay_skip_current_error_validates_command_accounts_and_signal():
    signal = threading.Event()
    task = {
        "status": "running",
        "command": "gopay-bind",
        "params": {"account_emails": ["first@example.com", "second@example.com"]},
    }

    assert gopay_skip_current_error(task, signal) == ""
    assert gopay_skip_current_error({**task, "status": "completed"}, signal) == "任务当前状态 completed 无法跳过"
    assert gopay_skip_current_error({**task, "command": "register"}, signal) == "当前任务不支持跳过账号"
    assert gopay_skip_current_error({**task, "params": {"account_emails": ["only@example.com"]}}, signal) == "当前 GoPay 任务没有下一个账号可切换"
    assert gopay_skip_current_error(task, None) == "当前 GoPay 任务不支持跳过账号"


def test_mark_task_skip_current_requested_sets_signal_and_task_flag():
    task = {"task_id": "task-1", "command": "gopay-bind", "task_group": TASK_GROUP_GOPAY}
    signal = threading.Event()

    mark_task_skip_current_requested(task, signal)

    assert signal.is_set()
    assert task["skip_current_requested"] is True
    assert gopay_skip_current_progress_event() == {
        "stage": "gopay_skip_current_requested",
        "message": "已请求跳过当前账号，等待当前步骤在安全点退出后切换下一个账号",
    }
    assert gopay_skip_current_response(task) == {
        "message": "已请求跳过当前账号，等待切换下一个账号",
        "task_id": "task-1",
        "command": "gopay-bind",
        "task_group": TASK_GROUP_GOPAY,
    }


def test_apply_gopay_runtime_control_public_updates_merges_public_params_and_updates_message():
    task = {
        "params": {
            "account_emails": ["First@Example.com"],
            "gopay_concurrency": 1,
        }
    }
    updates = {
        "version": 2,
        "gopay_concurrency": 3,
        "gopay_auto_signup_sms_provider": "hero_sms",
        "gopay_balance_poll_interval_seconds": 7.0,
        "gopay_transfer_balance_wait_seconds": 45.0,
    }

    apply_gopay_runtime_control_public_updates(
        task,
        updates,
        ["second@example.com"],
    )

    assert updates["added_account_emails"] == ["second@example.com"]
    assert task["params"] == {
        "account_emails": ["first@example.com", "second@example.com"],
        "gopay_concurrency": 3,
        "gopay_auto_signup_sms_provider": "hero_sms",
        "gopay_balance_poll_interval_seconds": 7.0,
        "gopay_transfer_balance_wait_seconds": 45.0,
    }
    assert gopay_runtime_control_update_message(updates, ["second@example.com"]) == (
        "GoPay 热切换已应用：并发 3，短信服务商 hero_sms，余额查询间隔 7.0s，转账到账等待 45.0s，追加账号 1 个"
    )
    assert gopay_runtime_control_progress_event(updates, ["second@example.com"]) == {
        "stage": "gopay_runtime_control_updated",
        "updates": updates,
        "message": "GoPay 热切换已应用：并发 3，短信服务商 hero_sms，余额查询间隔 7.0s，转账到账等待 45.0s，追加账号 1 个",
        "level": "success",
    }


def test_busy_task_detail_uses_special_running_task():
    detail = busy_task_detail(
        "busy",
        {},
        {},
        current_task_id=None,
        special_running_task={"task_id": "admin-login", "command": "admin-login", "started_at": None},
    )

    assert detail == {
        "message": "busy",
        "running_task": {"task_id": "admin-login", "command": "admin-login", "started_at": None},
    }


def test_busy_task_detail_resolves_group_running_task():
    tasks = {
        "task-1": {
            "task_id": "task-1",
            "command": "register",
            "task_group": TASK_GROUP_REGISTER,
            "started_at": 12.0,
        }
    }
    current_task_ids = {TASK_GROUP_REGISTER: "task-1"}

    detail = busy_task_detail("busy", tasks, current_task_ids, current_task_id="global", task_group=TASK_GROUP_REGISTER)

    assert detail == {
        "message": "busy",
        "running_task": {
            "task_id": "task-1",
            "command": "register",
            "task_group": TASK_GROUP_REGISTER,
            "started_at": 12.0,
        },
    }


def test_busy_task_detail_falls_back_to_global_task_id_when_task_missing():
    detail = busy_task_detail("busy", {}, {}, current_task_id="global-task")

    assert detail == {
        "message": "busy",
        "running_task": {
            "task_id": "global-task",
            "command": "unknown",
            "task_group": None,
            "started_at": None,
        },
    }


def test_current_task_id_for_group_prefers_thread_task_then_group_then_global():
    current_task_ids = {TASK_GROUP_REGISTER: "group-task"}

    assert (
        current_task_id_for_group(
            thread_task_id="thread-task",
            current_task_ids=current_task_ids,
            current_task_id="global-task",
            task_group=TASK_GROUP_REGISTER,
        )
        == "thread-task"
    )
    assert (
        current_task_id_for_group(
            thread_task_id=None,
            fallback_task_id="submitted-task",
            current_task_ids=current_task_ids,
            current_task_id="global-task",
            task_group=TASK_GROUP_REGISTER,
        )
        == "submitted-task"
    )
    assert (
        current_task_id_for_group(
            thread_task_id=None,
            current_task_ids=current_task_ids,
            current_task_id="global-task",
            task_group=TASK_GROUP_REGISTER,
        )
        == "group-task"
    )
    assert (
        current_task_id_for_group(
            thread_task_id=None,
            current_task_ids=current_task_ids,
            current_task_id="global-task",
            task_group=None,
        )
        == "global-task"
    )


def test_current_task_index_activation_and_clear_preserves_unrelated_running_task():
    current_task_ids = {TASK_GROUP_REGISTER: "old-register", TASK_GROUP_GOPAY: "gopay-task"}

    current_task_id = activate_current_task_index(current_task_ids, TASK_GROUP_REGISTER, "new-register")
    current_task_id = clear_current_task_index(
        current_task_ids,
        current_task_id=current_task_id,
        task_group=TASK_GROUP_GOPAY,
        task_id="other-task",
    )

    assert current_task_id == "new-register"
    assert current_task_ids == {TASK_GROUP_REGISTER: "new-register", TASK_GROUP_GOPAY: "gopay-task"}

    current_task_id = clear_current_task_index(
        current_task_ids,
        current_task_id=current_task_id,
        task_group=TASK_GROUP_REGISTER,
        task_id="new-register",
    )

    assert current_task_id is None
    assert current_task_ids == {TASK_GROUP_REGISTER: None, TASK_GROUP_GOPAY: "gopay-task"}


def test_create_task_record_matches_api_task_shape():
    task = create_task_record(
        "login:user@example.com",
        {"email": "user@example.com"},
        exclusive=False,
        task_id="task-fixed",
        now=123.0,
    )

    assert task == {
        "task_id": "task-fixed",
        "command": "login:user@example.com",
        "task_group": TASK_GROUP_OAUTH,
        "params": {"email": "user@example.com"},
        "exclusive": False,
        "status": "pending",
        "created_at": 123.0,
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "progress": None,
        "progress_events": [],
    }


def test_create_task_record_preserves_preacquired_lock_marker():
    task = create_task_record("register", {}, group_lock_preacquired=True)

    assert task["task_group"] == TASK_GROUP_REGISTER
    assert task["_group_lock_preacquired"] is True


def test_prepare_task_start_registers_task_cancel_signal_and_prunes_history():
    tasks = {
        "old": {"task_id": "old", "created_at": 1.0, "status": "completed"},
        "running": {"task_id": "running", "created_at": 2.0, "status": "running"},
    }
    cancel_signals = {}
    cancel_event = threading.Event()

    task = prepare_task_start(
        tasks,
        cancel_signals,
        "register",
        {"count": 1},
        task_group=TASK_GROUP_REGISTER,
        group_lock_preacquired=True,
        cancel_event_factory=lambda: cancel_event,
        task_id="new",
        now=3.0,
        max_history=2,
    )

    assert task["task_id"] == "new"
    assert task["params"] == {"count": 1}
    assert task["task_group"] == TASK_GROUP_REGISTER
    assert task["_group_lock_preacquired"] is True
    assert cancel_signals == {"new": cancel_event}
    assert set(tasks) == {"running", "new"}


def test_ensure_task_cancel_event_reuses_existing_event():
    existing = threading.Event()
    signals = {"task-1": existing}

    event = ensure_task_cancel_event(signals, " task-1 ", cancel_event_factory=threading.Event)

    assert event is existing
    assert signals == {"task-1": existing}


def test_ensure_task_cancel_event_creates_missing_event():
    created = threading.Event()
    signals = {}

    event = ensure_task_cancel_event(signals, "task-1", cancel_event_factory=lambda: created)

    assert event is created
    assert signals == {"task-1": created}


def test_ensure_task_cancel_event_ignores_empty_task_id():
    created = threading.Event()
    signals = {}

    event = ensure_task_cancel_event(signals, "", cancel_event_factory=lambda: created)

    assert event is created
    assert signals == {}


def test_runtime_control_reads_and_creates_control():
    controls = {}
    lock = threading.RLock()

    assert runtime_control(controls, lock, "missing") == {}
    created = runtime_control(controls, lock, "task-1", create=True)
    created["value"] = 1

    assert runtime_control(controls, lock, "task-1") == {"value": 1}
    assert runtime_control(controls, lock, "") == {}


def test_init_gopay_runtime_control_sets_defaults_once():
    controls = {}
    lock = threading.RLock()

    first = init_gopay_runtime_control(
        controls,
        lock,
        "task-1",
        gopay_concurrency=2,
        sms_provider="smscloud",
        account_emails=["First@Example.com", "first@example.com", "second@example.com"],
        balance_poll_interval_seconds=5.0,
        transfer_balance_wait_seconds=60.0,
    )
    second = init_gopay_runtime_control(
        controls,
        lock,
        "task-1",
        gopay_concurrency=5,
        sms_provider="hero_sms",
        account_emails=["third@example.com"],
        balance_poll_interval_seconds=9.0,
        transfer_balance_wait_seconds=90.0,
    )

    assert first["all_account_emails"] == ["first@example.com", "second@example.com"]
    assert second["gopay_concurrency"] == 2
    assert second["gopay_auto_signup_sms_provider"] == "smscloud"
    assert second["version"] == 0


def test_update_gopay_runtime_control_applies_updates_and_appends_new_accounts():
    controls = {
        "task-1": {
            "pending_account_emails": [],
            "all_account_emails": ["first@example.com"],
            "version": 2,
        }
    }
    lock = threading.RLock()

    result = update_gopay_runtime_control(
        controls,
        lock,
        "task-1",
        gopay_concurrency=4,
        sms_provider="hero_sms",
        balance_poll_interval_seconds=7.0,
        transfer_balance_wait_seconds=45.0,
        account_emails=["First@Example.com", "second@example.com"],
    )

    assert result["added_emails"] == ["second@example.com"]
    assert result["updates"] == {
        "gopay_concurrency": 4,
        "gopay_auto_signup_sms_provider": "hero_sms",
        "gopay_balance_poll_interval_seconds": 7.0,
        "gopay_transfer_balance_wait_seconds": 45.0,
        "version": 3,
    }
    assert controls["task-1"]["pending_account_emails"] == ["second@example.com"]
    assert controls["task-1"]["all_account_emails"] == ["first@example.com", "second@example.com"]


def test_update_gopay_runtime_control_without_task_id_is_noop():
    controls = {}
    lock = threading.RLock()

    result = update_gopay_runtime_control(controls, lock, "", gopay_concurrency=4)

    assert result == {"control": {}, "updates": {}, "added_emails": []}
    assert controls == {}


def test_drain_gopay_pending_account_emails_clears_pending_and_dedupes_existing():
    controls = {
        "task-1": {
            "pending_account_emails": ["First@Example.com", "second@example.com", "second@example.com"],
        }
    }
    existing = {"first@example.com"}

    drained = drain_gopay_pending_account_emails(controls, threading.RLock(), "task-1", existing)

    assert drained == ["second@example.com"]
    assert existing == {"first@example.com", "second@example.com"}
    assert controls["task-1"]["pending_account_emails"] == []


def test_drain_gopay_pending_account_emails_without_control_is_noop():
    controls = {"task-1": {"pending_account_emails": ["first@example.com"]}}
    existing = set()

    assert drain_gopay_pending_account_emails(controls, threading.RLock(), "", existing) == []
    assert drain_gopay_pending_account_emails(controls, threading.RLock(), "missing", existing) == []
    assert controls["task-1"]["pending_account_emails"] == ["first@example.com"]


def test_clear_task_runtime_state_removes_only_target_task_state():
    skip_signals = {"task-1": object(), "task-2": object()}
    cancel_signals = {"task-1": object(), "task-2": object()}
    cancel_hooks = {"task-1": [lambda: None], "task-2": [lambda: None]}
    controls = {"task-1": {"value": 1}, "task-2": {"value": 2}}
    hooks_lock = threading.RLock()
    controls_lock = threading.RLock()

    clear_task_runtime_state(
        "task-1",
        skip_signals=skip_signals,
        cancel_signals=cancel_signals,
        cancel_hooks=cancel_hooks,
        cancel_hooks_lock=hooks_lock,
        controls=controls,
        controls_lock=controls_lock,
    )

    assert set(skip_signals) == {"task-2"}
    assert set(cancel_signals) == {"task-2"}
    assert set(cancel_hooks) == {"task-2"}
    assert set(controls) == {"task-2"}


def test_clear_task_runtime_state_without_task_id_is_noop():
    skip_signals = {"task-1": object()}
    cancel_signals = {"task-1": object()}
    cancel_hooks = {"task-1": [lambda: None]}
    controls = {"task-1": {"value": 1}}

    clear_task_runtime_state(
        "",
        skip_signals=skip_signals,
        cancel_signals=cancel_signals,
        cancel_hooks=cancel_hooks,
        cancel_hooks_lock=threading.RLock(),
        controls=controls,
        controls_lock=threading.RLock(),
    )

    assert set(skip_signals) == {"task-1"}
    assert set(cancel_signals) == {"task-1"}
    assert set(cancel_hooks) == {"task-1"}
    assert set(controls) == {"task-1"}


def test_prune_task_history_deletes_old_completed_or_failed_tasks_only():
    tasks = {
        "running-old": {"created_at": 1.0, "status": "running"},
        "completed-old": {"created_at": 2.0, "status": "completed"},
        "failed-old": {"created_at": 3.0, "status": "failed"},
        "completed-new": {"created_at": 4.0, "status": "completed"},
    }

    deleted = prune_task_history(tasks, 2)

    assert deleted == ["completed-old"]
    assert set(tasks) == {"running-old", "failed-old", "completed-new"}


def test_task_lifecycle_marks_running_and_prestart_cancelled():
    task = create_task_record("register", {}, task_id="task-1", now=1.0)

    mark_task_running(task, now=2.0)
    assert task["status"] == "running"
    assert task["started_at"] == 2.0

    mark_task_prestart_cancelled(task, now=3.0)
    assert task["status"] == "cancelled"
    assert task["result"] == {"status": "cancelled", "message": "任务启动前已取消"}
    assert task["finished_at"] == 3.0


def test_task_run_prestart_cancelled_marks_task_and_clears_current_index():
    task = create_task_record("register", {}, task_id="task-1", now=1.0)
    current_task_ids = {TASK_GROUP_REGISTER: "task-1", TASK_GROUP_GOPAY: "task-2"}

    current_task_id = mark_task_run_prestart_cancelled(
        task,
        "task-1",
        current_task_ids=current_task_ids,
        current_task_id="task-1",
        task_group=TASK_GROUP_REGISTER,
        now=3.0,
    )

    assert task["status"] == "cancelled"
    assert task["finished_at"] == 3.0
    assert current_task_id is None
    assert current_task_ids == {TASK_GROUP_REGISTER: None, TASK_GROUP_GOPAY: "task-2"}


def test_task_run_finished_marks_task_and_optionally_clears_current_index():
    task = create_task_record("register", {}, task_id="task-1", now=1.0)
    current_task_ids = {TASK_GROUP_REGISTER: "task-1"}

    current_task_id = mark_task_run_finished(
        task,
        "task-1",
        current_task_ids=current_task_ids,
        current_task_id="task-1",
        task_group=TASK_GROUP_REGISTER,
        now=4.0,
    )

    assert task["finished_at"] == 4.0
    assert current_task_id is None
    assert current_task_ids == {TASK_GROUP_REGISTER: None}
    assert mark_task_run_finished(task, "task-1", current_task_id="other", now=5.0) == "other"
    assert task["finished_at"] == 5.0


def test_task_lifecycle_marks_completed_or_cancelled_success():
    task = create_task_record("check", {}, task_id="task-1", now=1.0)

    mark_task_completed(task, {"ok": True}, is_cancelled=True)
    mark_task_finished(task, now=4.0)

    assert task["status"] == "cancelled"
    assert task["result"] == {"ok": True}
    assert task["finished_at"] == 4.0


def test_task_lifecycle_marks_failed_with_structured_task_result():
    task = create_task_record("check", {}, task_id="task-1", now=1.0)

    class StructuredError(RuntimeError):
        task_result = {"status": "failed", "stage": "checkout"}

    mark_task_failed(task, StructuredError("boom"), is_cancelled=False)
    mark_task_finished(task, now=5.0)

    assert task["status"] == "failed"
    assert task["result"] == {"status": "failed", "stage": "checkout"}
    assert task["error"] == "boom"
    assert task["finished_at"] == 5.0


def test_task_lifecycle_marks_cancelled_failure_without_structured_result():
    task = create_task_record("check", {}, task_id="task-1", now=1.0)

    mark_task_failed(task, RuntimeError("stopped"), is_cancelled=True)

    assert task["status"] == "cancelled"
    assert task["result"] is None
    assert task["error"] == "stopped"


def test_execute_task_callable_marks_completed_result():
    task = create_task_record("check", {}, task_id="task-1", now=1.0)

    error = execute_task_callable(task, "task-1", lambda value: {"value": value}, ("ok",), is_cancelled=lambda: False)

    assert error is None
    assert task["status"] == "completed"
    assert task["result"] == {"value": "ok"}


def test_execute_task_callable_passes_task_id_when_requested():
    task = create_task_record("check", {}, task_id="task-1", now=1.0)

    error = execute_task_callable(task, "task-1", lambda task_id, value: {"task_id": task_id, "value": value}, ("ok",), pass_task_id=True, is_cancelled=lambda: False)

    assert error is None
    assert task["result"] == {"task_id": "task-1", "value": "ok"}


def test_execute_task_callable_marks_cancelled_after_success_when_cancelled():
    task = create_task_record("check", {}, task_id="task-1", now=1.0)

    error = execute_task_callable(task, "task-1", lambda: {"ok": True}, is_cancelled=lambda: True)

    assert error is None
    assert task["status"] == "cancelled"
    assert task["result"] == {"ok": True}


def test_execute_task_callable_marks_failed_and_returns_exception():
    task = create_task_record("check", {}, task_id="task-1", now=1.0)

    class StructuredError(RuntimeError):
        task_result = {"status": "failed", "stage": "worker"}

    error = execute_task_callable(task, "task-1", lambda: (_ for _ in ()).throw(StructuredError("boom")), is_cancelled=lambda: False)

    assert isinstance(error, StructuredError)
    assert task["status"] == "failed"
    assert task["result"] == {"status": "failed", "stage": "worker"}
    assert task["error"] == "boom"


def test_interrupted_task_snapshot_marks_cancelled_and_caps_progress_events():
    snapshot = interrupted_task_snapshot(
        {
            "task_id": "task-1",
            "status": "running",
            "progress": {"stage": "old"},
            "progress_events": [{"stage": f"old-{index}"} for index in range(305)],
        },
        now=123.0,
        event_id="event-fixed",
    )

    assert snapshot["status"] == "cancelled"
    assert snapshot["finished_at"] == 123.0
    assert snapshot["progress"]["stage"] == "task_interrupted_on_startup"
    assert snapshot["progress"]["event_id"] == "event-fixed"
    assert len(snapshot["progress_events"]) == 300
    assert snapshot["progress_events"][-1]["event_id"] == "event-fixed"


def test_append_task_progress_event_adds_worker_context_and_updates_progress():
    task = {
        "task_id": "task-worker",
        "command": "gopay-pro",
        "progress": {"stage": "old", "unchanged": True},
        "progress_events": [],
    }

    event = append_task_progress_event(
        task,
        {"stage": "running", "message": "binding wallet"},
        now=321.0,
        event_id="event-worker",
        worker_label="worker-2",
        worker_index=2,
    )

    assert event["event_id"] == "event-worker"
    assert event["updated_at"] == 321.0
    assert event["worker"] == "worker-2"
    assert event["worker_label"] == "worker-2"
    assert event["worker_index"] == 2
    assert event["message"] == "[worker-2] binding wallet"
    assert task["progress"]["unchanged"] is True
    assert task["progress"]["stage"] == "running"
    assert task["progress_events"] == [event]


def test_append_task_progress_event_does_not_double_prefix_worker_message():
    task = {"task_id": "task-worker", "command": "gopay-pro", "progress_events": []}

    event = append_task_progress_event(
        task,
        {"message": "[worker-2] already tagged"},
        now=321.0,
        event_id="event-worker",
        worker_label="worker-2",
        worker_index=2,
    )

    assert event["message"] == "[worker-2] already tagged"


def test_append_task_progress_event_caps_default_task_events():
    task = {
        "task_id": "task-default",
        "command": "check",
        "progress_events": [{"event_id": f"old-{index}"} for index in range(300)],
    }

    append_task_progress_event(task, {"stage": "new"}, now=1.0, event_id="new-event")

    assert len(task["progress_events"]) == 300
    assert task["progress_events"][0]["event_id"] == "old-1"
    assert task["progress_events"][-1]["event_id"] == "new-event"


def test_append_task_progress_event_keeps_extended_command_history():
    task = {
        "task_id": "task-register",
        "command": "register",
        "progress_events": [{"event_id": f"old-{index}"} for index in range(2000)],
    }

    append_task_progress_event(task, {"stage": "new"}, now=1.0, event_id="new-event")

    assert len(task["progress_events"]) == 2000
    assert task["progress_events"][0]["event_id"] == "old-1"
    assert task["progress_events"][-1]["event_id"] == "new-event"


def test_append_live_task_progress_ignores_blank_or_missing_task_id():
    live_tasks = {"task-1": {"task_id": "task-1", "command": "check", "progress_events": []}}

    assert append_live_task_progress(live_tasks, "", {"stage": "ignored"}) is None
    assert append_live_task_progress(live_tasks, "missing", {"stage": "ignored"}) is None
    assert live_tasks["task-1"]["progress_events"] == []


def test_append_live_task_progress_appends_to_matching_task_with_worker_context():
    task = {"task_id": "task-1", "command": "gopay-pro", "progress_events": []}
    live_tasks = {"task-1": task}

    updated = append_live_task_progress(
        live_tasks,
        " task-1 ",
        {"stage": "binding", "message": "bind wallet"},
        worker_label="worker-3",
        worker_index=3,
    )

    assert updated is task
    assert task["progress"]["stage"] == "binding"
    assert task["progress"]["message"] == "[worker-3] bind wallet"
    assert task["progress_events"][0]["worker_label"] == "worker-3"


def test_register_task_cancel_hook_unregisters_hook():
    hooks = {}
    signals = {}
    lock = threading.RLock()
    called = []

    unregister = register_task_cancel_hook(hooks, signals, lock, " task-1 ", lambda: called.append("hook"))
    unregister()

    assert hooks == {}
    assert run_task_cancel_hooks(hooks, lock, "task-1") == 0
    assert called == []


def test_register_task_cancel_hook_runs_late_registration_immediately():
    hooks = {}
    cancel_event = threading.Event()
    cancel_event.set()
    signals = {"task-1": cancel_event}
    lock = threading.RLock()
    called = []

    unregister = register_task_cancel_hook(hooks, signals, lock, "task-1", lambda: called.append("hook"))
    unregister()

    assert called == ["hook"]
    assert hooks == {}


def test_run_task_cancel_hooks_consumes_hooks_and_reports_errors():
    hooks = {}
    signals = {}
    lock = threading.RLock()
    called = []
    errors = []

    def broken_hook():
        raise RuntimeError("boom")

    register_task_cancel_hook(hooks, signals, lock, "task-1", broken_hook)
    register_task_cancel_hook(hooks, signals, lock, "task-1", lambda: called.append("second"))

    count = run_task_cancel_hooks(hooks, lock, "task-1", on_error=lambda task_id, stage: errors.append((task_id, stage)))

    assert count == 2
    assert hooks == {}
    assert called == ["second"]
    assert errors == [("task-1", "cancel")]


def test_clear_task_cancel_hooks_removes_only_target_task():
    hooks = {"task-1": [lambda: None], "task-2": [lambda: None]}
    lock = threading.RLock()

    clear_task_cancel_hooks(hooks, lock, "task-1")

    assert set(hooks) == {"task-2"}


def test_task_snapshot_store_persists_and_loads_with_orphan_cancellation(tmp_path, monkeypatch):
    db_path = tmp_path / "tasks.sqlite3"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_path))
    task = {
        "task_id": "task-store",
        "command": "register",
        "task_group": TASK_GROUP_REGISTER,
        "status": "running",
        "created_at": 100.0,
        "started_at": 101.0,
        "finished_at": None,
        "progress": {"stage": "running"},
        "progress_events": [],
    }

    persist_task_snapshot(task, owner_pid=999999)

    loaded = load_task_snapshots(10, process_checker=lambda _pid: False, now=200.0)

    assert loaded[0]["task_id"] == "task-store"
    assert loaded[0]["status"] == "cancelled"
    assert loaded[0]["finished_at"] == 200.0

    from autotoken import sqlite_store

    with sqlite_store.connect() as conn:
        row = conn.execute("SELECT status, data FROM task_snapshots WHERE task_id = ?", ("task-store",)).fetchone()
    assert row["status"] == "cancelled"
    stored = json.loads(row["data"])
    assert stored["error"] == "后端已重启，旧任务已中断"


def test_cancel_orphaned_task_snapshots_marks_only_dead_owner(tmp_path, monkeypatch):
    db_path = tmp_path / "tasks.sqlite3"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_path))
    persist_task_snapshot(
        {"task_id": "dead", "command": "check", "status": "running", "created_at": 10.0},
        owner_pid=100,
    )
    persist_task_snapshot(
        {"task_id": "alive", "command": "check", "status": "running", "created_at": 11.0},
        owner_pid=200,
    )

    count = cancel_orphaned_task_snapshots(process_checker=lambda pid: int(pid or 0) == 200, now=300.0)

    assert count == 1
    from autotoken import sqlite_store

    with sqlite_store.connect() as conn:
        rows = {
            row["task_id"]: row["status"]
            for row in conn.execute("SELECT task_id, status FROM task_snapshots").fetchall()
        }
    assert rows == {"dead": "cancelled", "alive": "running"}


def test_merged_task_snapshots_prefers_live_task_over_persisted(tmp_path, monkeypatch):
    db_path = tmp_path / "tasks.sqlite3"
    monkeypatch.setenv("AUTOTOKEN_DB_FILE", str(db_path))
    persist_task_snapshot(
        {"task_id": "same", "command": "check", "status": "completed", "created_at": 10.0},
        owner_pid=123,
    )
    live = {
        "same": {
            "task_id": "same",
            "command": "check",
            "status": "running",
            "created_at": 20.0,
            "progress_events": [{"stage": "live"}],
        }
    }

    merged = merged_task_snapshots(live, limit=10, compact=True, process_checker=lambda _pid: True)

    assert len(merged) == 1
    assert merged[0]["status"] == "running"
    assert merged[0]["progress_event_count"] == 1


def test_task_detail_snapshot_prefers_live_task_over_persisted_snapshot():
    live = {
        "same": {
            "task_id": "same",
            "command": "check",
            "status": "running",
            "created_at": 20.0,
            "progress_events": [{"stage": "live"}],
        }
    }
    persisted = [{"task_id": "same", "command": "check", "status": "completed", "created_at": 10.0}]

    detail = task_detail_snapshot(live, " same ", persisted)

    assert detail["status"] == "running"
    assert detail["progress_events"] == [{"stage": "live"}]


def test_task_detail_snapshot_falls_back_to_persisted_snapshot():
    persisted = [{"task_id": "persisted", "command": "check", "status": "completed", "created_at": 10.0}]

    assert task_detail_snapshot({}, "persisted", persisted) == persisted[0]


def test_task_detail_snapshot_returns_none_for_blank_or_missing_task_id():
    persisted = [{"task_id": "persisted", "command": "check", "status": "completed"}]

    assert task_detail_snapshot({}, "", persisted) is None
    assert task_detail_snapshot({}, "missing", persisted) is None
