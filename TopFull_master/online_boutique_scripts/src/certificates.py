import numpy
from scipy import stats


def compute_gamma_certificates(samples, delta, alpha):
    # Fit a Gamma distribution to the chain samples.
    params = stats.gamma.fit(samples, method="mm")
    chain_99p = stats.gamma(*params).ppf(0.99)
    # print(f"[INFO] 99th percentile latency for the fitted distribution: {chain_99p}")

    # Perturbation to the params -- multiply each param by alpha * (1 + delta).
    perturbed_params = [alpha * (1 + delta) * param for param in params]
    # print(f"[INFO] Chain params: {params}, Perturbed: {perturbed_params}")

    # Find the 99p latency for the perturbed params.
    perturbed_chain_99p = stats.gamma(*perturbed_params).ppf(0.99)

    # Log details.
    sampled_99p = numpy.percentile(samples, 99)
    print(
        f"[INFO] 99p latency: fitted: {chain_99p}, perturbed: {perturbed_chain_99p}, sampled: {sampled_99p}"
    )

    return params, chain_99p, perturbed_params, perturbed_chain_99p
