CXX = g++
CXXFLAGS = -O2 -std=c++17 -Wall -Wno-unused-variable -pthread
SRCS = snafu_main.cpp snafu_value.cpp snafu_scope.cpp snafu_lexer.cpp snafu_parser.cpp snafu_eval.cpp snafu_prelude.cpp snafu_python.cpp
TARGET = snafu

# Try to find Python — optional
PYTHON_CFLAGS  := $(shell python3-config --includes 2>/dev/null)
PYTHON_LDFLAGS := $(shell python3-config --ldflags --embed 2>/dev/null)

ifneq ($(PYTHON_CFLAGS),)
  CXXFLAGS += -DSNAFU_HAS_PYTHON $(PYTHON_CFLAGS)
  LDFLAGS  += $(PYTHON_LDFLAGS)
endif

$(TARGET): $(SRCS) snafu.h snafu_python.h
	$(CXX) $(CXXFLAGS) -o $(TARGET) $(SRCS) $(LDFLAGS)

clean:
	rm -f $(TARGET) $(TARGET).exe *.obj *.o
