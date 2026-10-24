#pragma once
#include <optional>
#include <string>

namespace a2r {
enum class RenameState { Verified, Rejected, Unverified, Restored, RollbackUnverified, ReadFailed };
struct RenameResult { RenameState state; long result = 0; };

// Control-thread transaction. Read must reacquire the endpoint/property store;
// a previously opened COM store can retain a stale friendly-name snapshot.
// Do not attempt another write merely because the first one was rejected.
template<class Read, class Write, class Wait>
RenameResult renameVerified(const std::wstring& requested, Read read, Write write, Wait wait) {
    const auto previous = read();
    if (!previous) return {RenameState::ReadFailed};
    if (*previous == requested) return {RenameState::Verified};
    const long result = write(requested);
    std::optional<std::wstring> observed;
    for (int attempt = 0; attempt < 6; ++attempt) {
        if (attempt) wait();
        observed = read();
        if (observed && *observed == requested) return {RenameState::Verified};
        if (result < 0 && observed && *observed == *previous)
            return {RenameState::Rejected, result};
    }
    if (observed && *observed == *previous)
        return {RenameState::Rejected, result};
    if (!observed) return {RenameState::Unverified, result};
    // Roll back only a verified changed name, never a failed or unreadable write.
    const long rollback = write(*previous);
    for (int attempt = 0; attempt < 6; ++attempt) {
        if (attempt) wait();
        observed = read();
        if (observed && *observed == *previous) return {RenameState::Restored, result};
    }
    return {RenameState::RollbackUnverified, rollback};
}
}
