"use client";

import { useState } from "react";

export default function UnlockModal({
  onClose,
  onUnlock,
}: {
  onClose: () => void;
  onUnlock: (pin: string) => boolean;
}) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState(false);

  function submit() {
    if (onUnlock(pin)) {
      onClose();
    } else {
      setError(true);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-canvas/85 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xs rounded-2xl border border-line bg-surf p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-3 text-sm font-semibold text-ink">
          Enter PIN to edit
        </h3>
        <input
          autoFocus
          type="password"
          value={pin}
          onChange={(e) => {
            setPin(e.target.value);
            setError(false);
          }}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          className={`w-full rounded-lg border bg-canvas px-3 py-2 text-sm text-ink outline-none ${
            error
              ? "border-danger focus:border-danger"
              : "border-line focus:border-ember"
          }`}
        />
        {error && (
          <p className="mt-1.5 text-xs text-danger">Incorrect PIN</p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-sm text-ink-dim hover:bg-surf-high"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember hover:bg-ember-light"
          >
            Unlock
          </button>
        </div>
      </div>
    </div>
  );
}
