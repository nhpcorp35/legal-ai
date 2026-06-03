from engines.case_retrieval_spike import retrieve_matching_cases

results = retrieve_matching_cases(
    ["questions of fact"]
)

assert results

assert (
    results[0]["case_name"]
    != "Supreme Court of the State of New York"
)

print("CASE RETRIEVAL QUALITY PASSED")
