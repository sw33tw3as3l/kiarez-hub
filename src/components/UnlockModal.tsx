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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xs rounded-2xl border border-neutral-800 bg-neutral-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-3 text-sm font-semibold text-neutral-200">
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
          className={`w-full rounded-lg border bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none ${
            error
              ? "border-red-500/60 focus:border-red-500"
              : "border-neutral-800 focus:border-red-600"
          }`}
        />
        {error && (
          <p className="mt-1.5 text-xs text-red-400">Incorrect PIN</p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-sm text-neutral-400 hover:bg-neutral-800"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-500"
          >
            Unlock
          </button>
        </div>
      </div>
    </div>
  );
}
