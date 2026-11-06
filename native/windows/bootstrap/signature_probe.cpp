// Suite #49 Slice 125: native, read-only Authenticode observation of THIS executable.
// Windows chain verification without a separately protected publisher pin is NOT
// installer authentication, protected custody, privilege, consent, or approval.
#include <windows.h>
#include <wintrust.h>
#include <softpub.h>
#include <wincrypt.h>
#include "publisher_pin_evidence.h"

#include <array>
#include <iostream>
#include <string>
#include <vector>

namespace {
constexpr const char* kNoAuthority =
    "NO_INSTALLER_APPROVAL_PROVISIONING_SERVICE_RECEIPT_OR_LAUNCH_AUTHORITY";

// Deliberately non-authorizing signer metadata extraction from the executable's
// own embedded PKCS#7 message. Neither this evidence nor a caller-supplied pin
// authenticates the independently protected publisher policy or caller identity.
struct SignedObject final {
    HCERTSTORE store = nullptr;
    HCRYPTMSG message = nullptr;
    ~SignedObject() {
        if (message != nullptr) CryptMsgClose(message);
        if (store != nullptr) CertCloseStore(store, 0);
    }
    SignedObject() = default;
    SignedObject(const SignedObject&) = delete;
    SignedObject& operator=(const SignedObject&) = delete;
};
struct Certificate final {
    PCCERT_CONTEXT context = nullptr;
    ~Certificate() {
        if (context != nullptr) CertFreeCertificateContext(context);
    }
    Certificate() = default;
    Certificate(const Certificate&) = delete;
    Certificate& operator=(const Certificate&) = delete;
};
struct LocalBuffer final {
    void* value = nullptr;
    ~LocalBuffer() {
        if (value != nullptr) LocalFree(value);
    }
    LocalBuffer() = default;
    LocalBuffer(const LocalBuffer&) = delete;
    LocalBuffer& operator=(const LocalBuffer&) = delete;
};

bool hash_der_sha256(const BYTE* raw, DWORD length, std::string& result) {
    if (raw == nullptr || length == 0) return false;
    std::array<BYTE, 32> digest{};
    DWORD count = static_cast<DWORD>(digest.size());
    if (!CryptHashCertificate2(L"SHA256", 0, nullptr, raw, length,
                               digest.data(), &count) || count != digest.size())
        return false;
    constexpr char kHex[] = "0123456789abcdef";
    result.clear();
    result.reserve(64);
    for (const BYTE byte : digest) {
        result.push_back(kHex[byte >> 4]);
        result.push_back(kHex[byte & 15]);
    }
    return true;
}

bool inspect_embedded_signer_evidence(const wchar_t* own_executable) {
    if (own_executable == nullptr) return false;
    SignedObject signed_object;
    if (!CryptQueryObject(CERT_QUERY_OBJECT_FILE, own_executable,
                          CERT_QUERY_CONTENT_FLAG_PKCS7_SIGNED_EMBED,
                          CERT_QUERY_FORMAT_FLAG_BINARY, 0, nullptr,
                          nullptr, nullptr, &signed_object.store,
                          &signed_object.message, nullptr) ||
        signed_object.store == nullptr || signed_object.message == nullptr)
        return false;
    DWORD signer_length = 0;
    if (!CryptMsgGetParam(signed_object.message, CMSG_SIGNER_INFO_PARAM, 0,
                          nullptr, &signer_length) ||
        signer_length < sizeof(CMSG_SIGNER_INFO) || signer_length > 8192)
        return false;
    std::vector<BYTE> signer_bytes(signer_length);
    if (!CryptMsgGetParam(signed_object.message, CMSG_SIGNER_INFO_PARAM, 0,
                          signer_bytes.data(), &signer_length) ||
        signer_length < sizeof(CMSG_SIGNER_INFO))
        return false;
    const auto* signer = reinterpret_cast<const CMSG_SIGNER_INFO*>(signer_bytes.data());
    CERT_INFO lookup{};
    lookup.Issuer = signer->Issuer;
    lookup.SerialNumber = signer->SerialNumber;
    Certificate selected;
    selected.context = CertFindCertificateInStore(
        signed_object.store, X509_ASN_ENCODING | PKCS_7_ASN_ENCODING,
        0, CERT_FIND_SUBJECT_CERT, &lookup, nullptr);
    if (selected.context == nullptr || selected.context->pCertInfo == nullptr)
        return false;
    std::string cert_sha256;
    if (!hash_der_sha256(selected.context->pbCertEncoded,
                         selected.context->cbCertEncoded, cert_sha256))
        return false;
    LocalBuffer encoded_spki;
    DWORD spki_size = 0;
    if (!CryptEncodeObjectEx(
            X509_ASN_ENCODING, X509_PUBLIC_KEY_INFO,
            &selected.context->pCertInfo->SubjectPublicKeyInfo,
            CRYPT_ENCODE_ALLOC_FLAG, nullptr, &encoded_spki.value,
            &spki_size) || encoded_spki.value == nullptr)
        return false;
    std::string spki_sha256;
    if (!hash_der_sha256(static_cast<const BYTE*>(encoded_spki.value),
                         spki_size, spki_sha256))
        return false;
    return pds_publisher_pin_evidence::valid_signer_evidence(
        cert_sha256, spki_sha256);
}

// This result is an observation from a process controlled by its own caller.
// Neither a local trust chain nor this program is a trustworthy approval token.
bool own_authenticode_chain_observed(bool& evidence_observed) {
    evidence_observed = false;
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
    if (result != ERROR_SUCCESS) return false;
    evidence_observed = inspect_embedded_signer_evidence(path.data());
    return true;
}

void emit(const char* status, bool chain, bool evidence) {
    std::cout << "{\"status\":\"" << status
              << "\",\"wintrust_chain_observed\":" << (chain ? "true" : "false")
              << ",\"signer_evidence_observed\":" << (evidence ? "true" : "false")
              << ",\"publisher_pin_verified\":false,\"authorized_to_install\":false,"
              << "\"authority\":\"" << kNoAuthority << "\"}\n";
    std::cout << kNoAuthority << '\n';
}
} // namespace

int wmain(int argc, wchar_t* argv[]) {
    // No caller-selected binary, trusted root, signer pin, service or install mode.
    (void)argv;
    if (argc != 1) {
        emit("REFUSED_UNSUPPORTED_SIGNATURE_ARGUMENT", false, false);
        return 2;
    }
    bool evidence = false;
    const bool chain = own_authenticode_chain_observed(evidence);
    const bool observed = chain && evidence;
    emit(!chain ? "NATIVE_SIGNATURE_NOT_TRUSTED" :
         !evidence ? "NATIVE_SIGNATURE_EVIDENCE_UNAVAILABLE" :
                     "NATIVE_WINDOWS_CHAIN_OBSERVED_PIN_UNPROVISIONED",
         chain, evidence);
    // A valid local Windows signature never grants installer authorization.
    return observed ? 2 : 1;
}
