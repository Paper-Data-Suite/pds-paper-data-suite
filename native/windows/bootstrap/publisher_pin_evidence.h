// Suite #49 Slice 127: pure claimed-pin comparison with native signer evidence.
// Inputs are claims until an independent protected policy baseline exists.
// A matching claim is NEVER approval, installation or verified native custody.
#pragma once

#include "publisher_pin_contract.h"

#include <string_view>

namespace pds_publisher_pin_evidence {

enum class EvidenceComparison {
    invalid,
    claimed_mismatch,
    claimed_match_without_authority,
};

[[nodiscard]] inline bool canonical_sha256(std::string_view value) noexcept {
    if (value.size() != 64) return false;
    bool nonzero = false;
    for (const char c : value) {
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
            return false;
        if (c != '0') nonzero = true;
    }
    return nonzero;
}

[[nodiscard]] inline bool valid_signer_evidence(
    std::string_view certificate_sha256, std::string_view spki_sha256) noexcept {
    return canonical_sha256(certificate_sha256) && canonical_sha256(spki_sha256);
}

// Both signer evidence and claimed policy may be supplied by an untrusted caller.
// No result is equivalent to a publisher authorized by the operating system.
[[nodiscard]] inline EvidenceComparison compare_claimed_pin(
    std::string_view claimed_policy,
    std::string_view certificate_sha256,
    std::string_view spki_sha256) {
    pds_publisher_pin_contract::PublisherPin pin;
    if (!valid_signer_evidence(certificate_sha256, spki_sha256) ||
        !pds_publisher_pin_contract::parse_claimed_pin(claimed_policy, pin))
        return EvidenceComparison::invalid;
    if (pin.certificate_sha256 != certificate_sha256 ||
        pin.spki_sha256 != spki_sha256)
        return EvidenceComparison::claimed_mismatch;
    return EvidenceComparison::claimed_match_without_authority;
}
} // namespace pds_publisher_pin_evidence
