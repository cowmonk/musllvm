#include <atomic>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <thread>
#include <vector>

int
main()
{
	std::vector<int> values(128, 2);
	std::atomic<int> total{0};
	std::atomic<unsigned __int128> wide{0};
	std::thread worker([&]() { total.store(std::accumulate(values.begin(), values.end(), 0)); });

	worker.join();
	wide.store((unsigned __int128)1 << 100);
	if (wide.load() != (unsigned __int128)1 << 100)
		return 1;
	try {
		if (total.load() != 256)
			return 1;
		throw std::runtime_error("musllvm C++ OK");
	} catch (const std::runtime_error &error) {
		std::cout << error.what() << '\n';
	}
	std::cout.flush();
	return std::cout.good() ? 0 : 1;
}
