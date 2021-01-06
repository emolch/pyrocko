CC=nvcc
PROFILER=nvprof
VISUAL_PROFILER=nvvp

# profiles all sample invocations and generates reports in profiling/traces

profile_parstack_visual: profile_parstack 
	$(VISUAL_PROFILER) profiling/traces/parstack.nvprof

profile_minmax_visual: profile_minmax
	$(VISUAL_PROFILER) profiling/traces/minmax.nvprof

profile_parstack: profile_parstack.o parstack.o minmax.o utils.o 
	$(CC) -g -lineinfo -O3 -o profiling/bin/profile_parstack _build/profile_parstack.o _build/minmax.o _build/parstack.o _build/utils.o 
	$(PROFILER) --analysis-metrics -f -s -o profiling/traces/parstack.nvprof profiling/bin/profile_parstack

profile_minmax: profile_minmax.o minmax.o utils.o
	$(CC) -g -lineinfo -O3 -o profiling/bin/profile_minmax _build/profile_minmax.o _build/minmax.o _build/utils.o
	$(PROFILER) --analysis-metrics -f -s -o profiling/traces/minmax.nvprof profiling/bin/profile_minmax

profile_parstack.o: profiling/profile_parstack.cu
	$(CC) -g -lineinfo -O3 -c -o _build/profile_parstack.o profiling/profile_parstack.cu

profile_minmax.o: profiling/profile_minmax.cu
	$(CC) -g -lineinfo -O3 -c -o _build/profile_minmax.o profiling/profile_minmax.cu

parstack.o: parstack.cu
	$(CC) -g -lineinfo -O3 -c -o _build/parstack.o parstack.cu

minmax.o: minmax.cu
	$(CC) -g -lineinfo -O3 -c -o _build/minmax.o minmax.cu

utils.o: utils.cu
	$(CC) -g -lineinfo -O3 -c -o _build/utils.o utils.cu

clean:
	$(RM) profiling/traces/* _build/*
