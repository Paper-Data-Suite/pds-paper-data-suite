// Slice 124 native C++17 checkpoint/journal acceptance. No Windows privileges.
#include "checkpoint_contract.h"
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

namespace {
std::vector<std::uint8_t> bytes(const std::string& s) {
    return {s.begin(), s.end()};
}
bool check(bool ok, const char* name) {
    if (!ok) std::cerr << "NATIVE_CHECKPOINT_CONTRACT_FAILED: " << name << '\n';
    return ok;
}
} // namespace

int main() {
    using pds_checkpoint_contract::Relationship;
    using pds_checkpoint_contract::classify_claims;
    const std::string cp0 = R"PDS({"generation":0,"last_request_sha256":"0000000000000000000000000000000000000000000000000000000000000000","last_transaction_id":"00000000000000000000000000000000","lock_revision":0,"lock_sha256":"0000000000000000000000000000000000000000000000000000000000000000","registry_revision":0,"registry_sha256":"0000000000000000000000000000000000000000000000000000000000000000","schema":1,"trust_policy_revision":3,"trust_policy_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})PDS";
    const std::string cp1 = R"PDS({"generation":1,"last_request_sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","last_transaction_id":"dddddddddddddddddddddddddddddddd","lock_revision":7,"lock_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","registry_revision":5,"registry_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","schema":1,"trust_policy_revision":3,"trust_policy_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})PDS";
    const std::string journal0 = R"PDS({"phase":"INTENT_PREPARED","previous_checkpoint_sha256":"6ed3f658c9f5e57fe05865a398939d6130905f4d4f3739144987c4cb3571fe62","previous_generation":0,"proposed_checkpoint_sha256":"c5cd391f694db334be79a86225c4478c318d87ea6fd21d74c81af40974e7cd88","proposed_generation":1,"request_sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","schema":1,"transaction_id":"dddddddddddddddddddddddddddddddd"})PDS";
    const std::string journal1 = R"PDS({"phase":"CHECKPOINT_REPLACED_CLAIMED","previous_checkpoint_sha256":"6ed3f658c9f5e57fe05865a398939d6130905f4d4f3739144987c4cb3571fe62","previous_generation":0,"proposed_checkpoint_sha256":"c5cd391f694db334be79a86225c4478c318d87ea6fd21d74c81af40974e7cd88","proposed_generation":1,"request_sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","schema":1,"transaction_id":"dddddddddddddddddddddddddddddddd"})PDS";
    const std::string h0 = "6ed3f658c9f5e57fe05865a398939d6130905f4d4f3739144987c4cb3571fe62";
    const std::string h1 = "c5cd391f694db334be79a86225c4478c318d87ea6fd21d74c81af40974e7cd88";
    bool passed = true;
    auto reject = [&](const std::string& cp, const std::string& journal,
                      const std::string& digest, const char* name) {
        passed = check(classify_claims(bytes(cp), bytes(journal), digest) == Relationship::invalid,
                       name) && passed;
    };
    passed = check(classify_claims(bytes(cp0), bytes(journal0), h0) ==
                   Relationship::prepared_previous, "genesis-prepared") && passed;
    passed = check(classify_claims(bytes(cp1), bytes(journal0), h1) ==
                   Relationship::replacement_journal_unfinalized, "new-unfinalized") && passed;
    passed = check(classify_claims(bytes(cp1), bytes(journal1), h1) ==
                   Relationship::replacement_claimed_commit_unverified, "new-claimed") && passed;
    reject(cp0, journal1, h0, "replaced-with-genesis");
    reject(cp0, journal0, h1, "substituted-genesis-digest");
    reject(cp1, journal0, h0, "substituted-new-digest");
    reject(cp0, journal0 + "\n", h0, "noncanonical-journal");
    reject(" " + cp0, journal0, h0, "noncanonical-checkpoint");
    reject(cp0, journal0.substr(0, 9), h0, "truncated-journal");
    reject(cp0, std::string(4097, 'x'), h0, "oversized-journal");
    reject(std::string(4097, 'x'), journal0, h0, "oversized-checkpoint");
    reject(cp0, journal0, std::string(64, 'z'), "bad-digest-encoding");
    reject(cp0, journal0, std::string(64, '0'), "mismatched-digest");
    reject(cp0 + "\n", journal0, h0, "trailing-checkpoint");
    reject(cp0, journal0 + ",", h0, "extra-journal");
    reject(cp0, " " + journal0, h0, "noncanonical-phase-field");
    // Reconstruct untouched sample after the intentionally corrupted local copy.
    const std::string stable = R"PDS({"phase":"INTENT_PREPARED","previous_checkpoint_sha256":"6ed3f658c9f5e57fe05865a398939d6130905f4d4f3739144987c4cb3571fe62","previous_generation":0,"proposed_checkpoint_sha256":"c5cd391f694db334be79a86225c4478c318d87ea6fd21d74c81af40974e7cd88","proposed_generation":1,"request_sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","schema":1,"transaction_id":"dddddddddddddddddddddddddddddddd"})PDS";
    auto mutate = [&](const std::string& cp, const std::string& journal,
                      const std::string& old_text, const std::string& new_text,
                      bool checkpoint, const char* name) {
        std::string input = checkpoint ? cp : journal;
        const auto at = input.find(old_text);
        if (at == std::string::npos) { passed = check(false, name) && passed; return; }
        input.replace(at, old_text.size(), new_text);
        reject(checkpoint ? input : cp, checkpoint ? journal : input,
               cp == cp1 ? h1 : h0, name);
    };
    mutate(cp0, stable, "\"generation\":0", "\"generation\":true", true, "boolean-generation");
    mutate(cp0, stable, "\"schema\":1", "\"schema\":01", true, "leading-zero-schema");
    mutate(cp0, stable, "\"schema\":1", "\"schema\":2", true, "wrong-schema");
    mutate(cp0, stable, "\"trust_policy_revision\":3", "\"trust_policy_revision\":0", true, "zero-root-revision");
    mutate(cp0, stable, "\"generation\":0", "\"generation\":1", true, "forged-progress");
    mutate(cp0, stable, "\"generation\":0", "\"generation\":9007199254740992", true, "oversized-int");
    mutate(cp0, stable, "\"generation\":0", "\"generation\":0,\"generation\":0", true, "duplicate-json-field");
    mutate(cp0, stable, "\"last_request_sha256\":", "\"last_request_sha256\": ", true, "json-whitespace");
    mutate(cp0, stable, "\"trust_policy_sha256\":\"" + std::string(64, 'a'),
           "\"trust_policy_sha256\":\"" + std::string(64, 'A'), true, "uppercase-digest");
    mutate(cp0, stable, "\"trust_policy_revision\":3", "\"trust_policy_revision\":-1", true, "negative-revision");
    mutate(cp0, stable, "\"trust_policy_revision\":3", "\"trust_policy_revision\":3.0", true, "decimal-revision");
    mutate(cp0, stable, "\"trust_policy_revision\":3", "\"trust_policy_revision\":3e0", true, "exponent-revision");
    mutate(cp0, stable, "\"trust_policy_revision\":3", "\"trust_policy_revision\":null", true, "null-revision");
    mutate(cp0, stable, "\"generation\":0", "\"genera\\u0074ion\":0", true, "escaped-field");
    mutate(cp0, stable, "\"generation\":0", "\"extra\":0,\"generation\":0", true, "extra-json-field");
    mutate(cp0, stable, "\"generation\":0", "\"generation\":2", true, "unsupported-generation");
    mutate(cp0, stable, "\"generation\":0", "\"generation\":0 ", true, "trailing-number-space");
    mutate(cp0, stable, "\"phase\":\"INTENT_PREPARED\"", "\"phase\":\"COMMITTED\"", false, "unknown-phase");
    mutate(cp0, stable, "\"transaction_id\":\"" + std::string(32, 'd'),
           "\"transaction_id\":\"" + std::string(32, '0'), false, "zero-journal-transaction");
    mutate(cp0, stable, "\"previous_generation\":0", "\"previous_generation\":1", false, "bad-journal-previous-generation");
    mutate(cp0, stable, "\"proposed_generation\":1", "\"proposed_generation\":2", false, "bad-journal-proposed-generation");
    mutate(cp1, stable, "\"request_sha256\":\"" + std::string(64, 'e'),
           "\"request_sha256\":\"" + std::string(64, 'f'), false, "wrong-journal-request");
    mutate(cp1, stable, "\"proposed_checkpoint_sha256\":\"" + h1,
           "\"proposed_checkpoint_sha256\":\"" + std::string(64, 'f'), false, "altered-proposed-digest");
    if (!passed) return 1;
    std::cout << "SLICE124_NATIVE_CHECKPOINT_CONTRACT_TESTS_PASSED\n";
    return 0;
}
