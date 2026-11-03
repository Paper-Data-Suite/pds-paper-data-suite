// Suite #49 Slice 129. Observational primary-token eligibility signals only.
// This process cannot authenticate an independent administrator, provision trust,
// install software, write protected state, or authorize any action.
#include <windows.h>

#include <cstdint>
#include <iostream>
#include <utility>
#include <vector>

namespace {
constexpr const char* kNoAuthority =
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY";

class Handle final {
public:
    explicit Handle(HANDLE value = nullptr) noexcept : value_(value) {}
    ~Handle() { if (value_ != nullptr && value_ != INVALID_HANDLE_VALUE) CloseHandle(value_); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    [[nodiscard]] bool valid() const noexcept {
        return value_ != nullptr && value_ != INVALID_HANDLE_VALUE;
    }
    [[nodiscard]] HANDLE get() const noexcept { return value_; }
private:
    HANDLE value_;
};

class OwnedSid final {
public:
    explicit OwnedSid(PSID value = nullptr) noexcept : value_(value) {}
    ~OwnedSid() { if (value_ != nullptr) FreeSid(value_); }
    OwnedSid(const OwnedSid&) = delete;
    OwnedSid& operator=(const OwnedSid&) = delete;
    [[nodiscard]] PSID get() const noexcept { return value_; }
private:
    PSID value_;
};

struct TokenSignals {
    bool elevated = false;
    bool high_integrity = false;
    bool administrators_enabled = false;
};

bool observe_primary_token(TokenSignals& signals) {
    HANDLE raw = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_DUPLICATE, &raw))
        return false;
    const Handle primary(raw);
    TOKEN_ELEVATION elevation{};
    DWORD received = 0;
    if (!GetTokenInformation(primary.get(), TokenElevation, &elevation,
                             sizeof(elevation), &received) ||
        received != sizeof(elevation)) return false;

    DWORD needed = 0;
    (void)GetTokenInformation(primary.get(), TokenIntegrityLevel, nullptr,
                              0, &needed);
    if (GetLastError() != ERROR_INSUFFICIENT_BUFFER ||
        needed < sizeof(TOKEN_MANDATORY_LABEL) || needed > 2048) return false;
    std::vector<BYTE> buffer(needed);
    if (!GetTokenInformation(primary.get(), TokenIntegrityLevel, buffer.data(),
                             needed, &received) || received > needed ||
        received < sizeof(TOKEN_MANDATORY_LABEL)) return false;
    const auto* label = reinterpret_cast<const TOKEN_MANDATORY_LABEL*>(buffer.data());
    const PSID integrity = label->Label.Sid;
    if (integrity == nullptr || !IsValidSid(integrity)) return false;
    const PUCHAR count = GetSidSubAuthorityCount(integrity);
    if (count == nullptr || *count == 0) return false;
    const PDWORD rid = GetSidSubAuthority(integrity, static_cast<DWORD>(*count - 1));
    if (rid == nullptr) return false;

    HANDLE impersonation_raw = nullptr;
    if (!DuplicateToken(primary.get(), SecurityIdentification, &impersonation_raw))
        return false;
    const Handle impersonation(impersonation_raw);
    if (!impersonation.valid()) return false;
    SID_IDENTIFIER_AUTHORITY nt_authority = SECURITY_NT_AUTHORITY;
    PSID admin_raw = nullptr;
    if (!AllocateAndInitializeSid(&nt_authority, 2, SECURITY_BUILTIN_DOMAIN_RID,
                                  DOMAIN_ALIAS_RID_ADMINS, 0, 0, 0, 0, 0, 0,
                                  &admin_raw)) return false;
    const OwnedSid administrators(admin_raw);
    BOOL member = FALSE;
    if (!CheckTokenMembership(impersonation.get(), administrators.get(), &member))
        return false;
    signals.elevated = elevation.TokenIsElevated != 0;
    signals.high_integrity = *rid >= SECURITY_MANDATORY_HIGH_RID;
    signals.administrators_enabled = member != FALSE;
    return true;
}

void emit(const char* status, const TokenSignals& signals) {
    std::cout << "{\"status\":\"" << status
              << "\",\"token_elevation_observed\":"
              << (signals.elevated ? "true" : "false")
              << ",\"high_integrity_observed\":"
              << (signals.high_integrity ? "true" : "false")
              << ",\"administrators_group_enabled_observed\":"
              << (signals.administrators_enabled ? "true" : "false")
              << ",\"independent_administrator_authenticated\":false,"
              << "\"protected_provisioning_performed\":false,"
              << "\"publisher_pin_provisioned\":false,"
              << "\"rollback_protection_verified\":false,"
              << "\"authorized_to_install\":false,"
              << "\"authority\":\"" << kNoAuthority << "\"}\n";
    std::cout << kNoAuthority << '\n';
}
} // namespace

int wmain(int argc, wchar_t* argv[]) {
    (void)argv;
    const TokenSignals empty{};
    if (argc != 1) {
        emit("REFUSED_UNSUPPORTED_PROVISIONING_ARGUMENT", empty);
        return 2;
    }
    TokenSignals signals;
    if (!observe_primary_token(signals)) {
        emit("NATIVE_TOKEN_PREFLIGHT_UNAVAILABLE_NO_AUTHORITY", empty);
        return 1;
    }
    if (!(signals.elevated && signals.high_integrity &&
          signals.administrators_enabled)) {
        emit("NATIVE_TOKEN_PREFLIGHT_INSUFFICIENT_NO_AUTHORITY", signals);
        return 1;
    }
    emit("NATIVE_TOKEN_SIGNALS_OBSERVED_NO_AUTHORITY", signals);
    return 2;
}
