// Slice 126: native C++17 claimed publisher-pin schema / revision negative tests.
// These tests neither provision keys nor make signed/unsigned installation decisions.
#include "publisher_pin_contract.h"

#include <iostream>
#include <string>

namespace {
bool check(bool ok, const char* label) {
    if (!ok) std::cerr << "SLICE126_PUBLISHER_PIN_CONTRACT_FAILED: " << label << '\n';
    return ok;
}
} // namespace

int main() {
    using namespace pds_publisher_pin_contract;
    const std::string cert(64, 'a');
    const std::string spki(64, 'b');
    const std::string newer_cert(64, 'c');
    const auto make = [&](const std::string& c, const std::string& key,
                          const std::string& revision) {
        return std::string("{\"certificate_sha256\":\"") + c +
               "\",\"revision\":" + revision + ",\"schema\":1,\"spki_sha256\":\"" +
               key + "\"}";
    };
    const std::string baseline = make(cert, spki, "5");
    const std::string exact = make(cert, spki, "5");
    const std::string advanced = make(newer_cert, spki, "6");
    PublisherPin parsed;
    bool passed = true;
    passed = check(parse_claimed_pin(baseline, parsed) && parsed.revision == 5 &&
                   parsed.certificate_sha256 == cert && parsed.spki_sha256 == spki,
                   "strict-valid") && passed;
    passed = check(review_claimed_transition(baseline, exact) ==
                   ClaimedTransition::identical_claim_only, "same-revision-same-pin") && passed;
    passed = check(review_claimed_transition(baseline, advanced) ==
                   ClaimedTransition::rotation_claim_requires_independent_native_custody,
                   "rotation-claim-only") && passed;
    const auto reject = [&](const std::string& claim, const char* label) {
        PublisherPin pin;
        passed = check(!parse_claimed_pin(claim, pin), label) && passed;
    };
    reject("", "missing");
    reject("{}", "missing-keys");
    reject(" " + baseline, "leading-whitespace");
    reject(baseline + "\n", "trailing-whitespace");
    reject(std::string(513, 'x'), "oversized");
    reject(make(std::string(64, '0'), spki, "5"), "zero-cert");
    reject(make(cert, std::string(64, '0'), "5"), "zero-spki");
    reject(make(std::string(64, 'A'), spki, "5"), "uppercase-cert");
    reject(make(cert, spki, "0"), "zero-revision");
    reject(make(cert, spki, "05"), "leading-zero-revision");
    reject(make(cert, spki, "-1"), "negative-revision");
    reject(make(cert, spki, "5.0"), "floating-revision");
    reject(make(cert, spki, "9007199254740992"), "out-of-range-revision");
    reject(make(cert, spki, "true"), "boolean-revision");
    reject(make(cert, spki, "null"), "null-revision");
    reject(make(cert, spki, "5").replace(0, 1, "["), "array-root");
    reject(baseline.substr(0, baseline.size() - 1), "truncated");
    const auto edit = [&](const std::string& needle, const std::string& replacement,
                          const char* label) {
        std::string value = baseline;
        const auto pos = value.find(needle);
        if (pos == std::string::npos) {
            passed = check(false, label) && passed;
            return;
        }
        value.replace(pos, needle.size(), replacement);
        reject(value, label);
    };
    edit("\"schema\":1", "\"schema\":2", "schema2");
    edit("\"schema\":1", "\"schema\":1,\"schema\":1", "duplicate-key");
    edit("\"revision\":5", "\"revision\": 5", "noncanonical-space");
    edit("\"revision\":5", "\"revision\":5e0", "scientific-revision");
    edit("\"revision\":5", "\"revis\\u0069on\":5", "escaped-key");
    edit("\"schema\":1", "\"extra\":1,\"schema\":1", "extra-key");
    edit("\"spki_sha256\":", "\"SPKI_SHA256\":", "uppercase-key");
    passed = check(review_claimed_transition(baseline, make(newer_cert, spki, "5")) ==
                   ClaimedTransition::invalid, "equal-revision-equivocation") && passed;
    passed = check(review_claimed_transition(baseline, make(cert, spki, "4")) ==
                   ClaimedTransition::invalid, "revision-rollback") && passed;
    passed = check(review_claimed_transition(baseline, "{}") ==
                   ClaimedTransition::invalid, "untrusted-candidate") && passed;
    passed = check(review_claimed_transition("{}", advanced) ==
                   ClaimedTransition::invalid, "untrusted-baseline") && passed;
    if (!passed) return 1;
    std::cout << "SLICE126_NATIVE_PUBLISHER_PIN_CONTRACT_TESTS_PASSED\n";
    return 0;
}
