// Suite #49 Slice 125: native, read-only Authenticode observation of THIS executable.
// Windows chain verification without a separately protected publisher pin is NOT
// installer authentication, protected custody, privilege, consent, or approval.
#include <windows.h>
#include <wintrust.h>
#include <softpub.h>

#include <array>
#include <iostream>

namespace {
constexpr const char* kNoAuthority =
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY";

// This result is an observation from a process controlled by its own caller.
// Neither a local trust chain nor this program is a trustworthy approval token.
bool own_authenticode_chain_observed() {
    std::array<wchar_t, 32768> path{};
    const DWORD used = GetModuleFileNameW(nullptr, path.data(),
                                          static_cast<DWORD>(path.size()));
    if (used == 0 || used >= path.size()) return false;
    WINTRUST_FILE_INFO subject{};
    subject.cbStruct = sizeof(subject);
    subject.pcwszFilePath = path.data();
    WINTRUST_DATA request{};
    request.cbStruct = sizeof(request);
    request.dwUIChoice = WTD_UI_NONE;
    request.fdwRevocationChecks = WTD_REVOKE_WHOLECHAIN;
    request.dwUnionChoice = WTD_CHOICE_FILE;
    request.pFile = &subject;
    request.dwStateAction = WTD_STATEACTION_VERIFY;
    // Strictly offline. No HTTP revocation traffic or trust-store changes.
    request.dwProvFlags = WTD_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT |
                          WTD_CACHE_ONLY_URL_RETRIEVAL;
    request.dwUIContext = WTD_UICONTEXT_EXECUTE;
    GUID action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
    const LONG result = WinVerifyTrust(nullptr, &action, &request);
    request.dwStateAction = WTD_STATEACTION_CLOSE;
    (void)WinVerifyTrust(nullptr, &action, &request);
    return result == ERROR_SUCCESS;
}

void emit(const char* status, bool observed) {
    std::cout << "{\"status\":\"" << status
              << "\",\"wintrust_chain_observed\":" << (observed ? "true" : "false")
              << ",\"publisher_pin_verified\":false,\"authorized_to_install\":false,"
              << "\"authority\":\"" << kNoAuthority << "\"}\n";
    std::cout << kNoAuthority << '\n';
}
} // namespace

int wmain(int argc, wchar_t* argv[]) {
    // No caller-selected binary, trusted root, signer pin, service or install mode.
    (void)argv;
    if (argc != 1) {
        emit("REFUSED_UNSUPPORTED_SIGNATURE_ARGUMENT", false);
        return 2;
    }
    const bool observed = own_authenticode_chain_observed();
    emit(observed ? "NATIVE_WINDOWS_CHAIN_OBSERVED_PIN_UNPROVISIONED" :
                    "NATIVE_SIGNATURE_NOT_TRUSTED", observed);
    // A valid local Windows signature never grants installer authorization.
    return observed ? 2 : 1;
}
