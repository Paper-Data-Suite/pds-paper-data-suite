// Slice 127: no native privileges; evidence-to-CLAIM comparison only.
#include "publisher_pin_evidence.h"

#include <iostream>
#include <string>

namespace {
bool check(bool ok, const char* label) {
    if (!ok) std::cerr << "SLICE127_PUBLISHER_EVIDENCE_FAILED: " << label << '\n';
    return ok;
}
} // namespace

int main() {
    using namespace pds_publisher_pin_evidence;
    const std::string a(64, 'a');
    const std::string b(64, 'b');
    const std::string c(64, 'c');
    const std::string policy =
        "{\"certificate_sha256\":\"" + a +
        "\",\"revision\":8,\"schema\":1,\"spki_sha256\":\"" + b + "\"}";
    bool passed = true;
    passed = check(valid_signer_evidence(a, b), "canonical-evidence") && passed;
    passed = check(!valid_signer_evidence(std::string(64, '0'), b),
                   "zero-certificate") && passed;
    passed = check(!valid_signer_evidence(a, std::string(64, '0')),
                   "zero-spki") && passed;
    passed = check(!valid_signer_evidence(std::string(64, 'A'), b),
                   "uppercase") && passed;
    passed = check(!valid_signer_evidence(a.substr(0, 63), b),
                   "short-evidence") && passed;
    passed = check(!valid_signer_evidence(a, b + "z"),
                   "long-evidence") && passed;
    passed = check(compare_claimed_pin(policy, a, b) ==
                   EvidenceComparison::claimed_match_without_authority,
                   "matching-claim-does-not-authorize") && passed;
    passed = check(compare_claimed_pin(policy, c, b) ==
                   EvidenceComparison::claimed_mismatch, "different-certificate") && passed;
    passed = check(compare_claimed_pin(policy, a, c) ==
                   EvidenceComparison::claimed_mismatch, "different-spki") && passed;
    passed = check(compare_claimed_pin("{}", a, b) ==
                   EvidenceComparison::invalid, "untrusted-malformed-policy") && passed;
    passed = check(compare_claimed_pin(policy, std::string(64, '0'), b) ==
                   EvidenceComparison::invalid, "malformed-evidence") && passed;
    passed = check(compare_claimed_pin(policy + "\n", a, b) ==
                   EvidenceComparison::invalid, "noncanonical-policy") && passed;
    if (!passed) return 1;
    std::cout << "SLICE127_NATIVE_PUBLISHER_EVIDENCE_TESTS_PASSED\n";
    return 0;
}
