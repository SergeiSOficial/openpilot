cmake_minimum_required(VERSION 3.22)
project(openpilot_android LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
get_filename_component(REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../../../.." ABSOLUTE)
set(MSGQ "${REPO_ROOT}/tools/android/.cache/msgq")
if(NOT EXISTS "${MSGQ}/msgq/android_path.h")
  message(FATAL_ERROR "Run tools/android/stage_msgq.py before building Android")
endif()
add_library(openpilot_ipc SHARED
  native_bridge.cc
  live_native.cc
  ${MSGQ}/msgq/ipc.cc
  ${MSGQ}/msgq/impl_msgq.cc
  ${MSGQ}/msgq/impl_fake.cc
  ${MSGQ}/msgq/msgq.cc
  ${MSGQ}/msgq/event.cc
  ${MSGQ}/msgq/visionipc/visionipc.cc
  ${MSGQ}/msgq/visionipc/visionipc_server.cc
  ${MSGQ}/msgq/visionipc/visionipc_client.cc
  ${MSGQ}/msgq/visionipc/visionbuf.cc)
target_include_directories(openpilot_ipc PRIVATE ${MSGQ})
target_link_libraries(openpilot_ipc android log EGL GLESv3 jnigraphics dl)

set(NATIVE_DEPS "${REPO_ROOT}/tools/android/.cache/native-deps")
if(EXISTS "${NATIVE_DEPS}/openpilot/cereal/gen/cpp/log.capnp.h")
  add_library(params_c SHARED
    ${REPO_ROOT}/openpilot/common/params_c.cc
    ${REPO_ROOT}/openpilot/common/params.cc
    ${REPO_ROOT}/openpilot/common/util.cc
    android_logging.cc)
  target_include_directories(params_c PRIVATE ${REPO_ROOT}/openpilot ${NATIVE_DEPS} ${NATIVE_DEPS}/include
    ${NATIVE_DEPS}/openpilot/cereal/gen/cpp)
  # CMake defines ANDROID=1, which collides with cereal's historical ANDROID enum.
  # The NDK's __ANDROID__ platform macro remains available.
  target_compile_options(params_c PRIVATE -UANDROID)
  if(ANDROID)
    target_link_libraries(params_c log)
  else()
    target_link_libraries(params_c pthread)
  endif()
endif()

set(GENERATED "${REPO_ROOT}/tools/android/.cache/generated")
if(EXISTS "${GENERATED}/locationd/pose.cpp" AND EXISTS "${NATIVE_DEPS}/eigen/eigen3/Eigen/Core")
  add_library(rednose_core STATIC
    ${REPO_ROOT}/rednose_repo/rednose/helpers/ekf_load.cc
    ${REPO_ROOT}/rednose_repo/rednose/helpers/ekf_sym.cc)
  set_target_properties(rednose_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
  target_include_directories(rednose_core PUBLIC ${REPO_ROOT}/rednose_repo ${REPO_ROOT}/rednose_repo/rednose
    ${NATIVE_DEPS}/eigen ${NATIVE_DEPS}/eigen/eigen3)
  target_link_libraries(rednose_core PUBLIC dl)
  foreach(model pose car)
    add_library(${model} SHARED ${GENERATED}/locationd/${model}.cpp)
    target_include_directories(${model} PRIVATE ${GENERATED}/locationd)
    target_link_libraries(${model} rednose_core)
  endforeach()
endif()

if(ANDROID OR HOST_ACADOS_DIR)
  if(ANDROID)
  set(ACADOS_DEPS "${NATIVE_DEPS}/acados/${ANDROID_ABI}")
  set(PYTHON_DEPS "${NATIVE_DEPS}/python/${ANDROID_ABI}")
  else()
    set(ACADOS_DEPS "${HOST_ACADOS_DIR}")
  endif()
  if(EXISTS "${ACADOS_DEPS}/lib/libacados.so" AND EXISTS "${GENERATED}/longitudinal_mpc/acados_ocp_solver_pyx.c")
    set(MPC "${GENERATED}/longitudinal_mpc")
    file(GLOB_RECURSE MPC_FUNCTIONS CONFIGURE_DEPENDS "${MPC}/long_model/*.c" "${MPC}/long_cost/*.c" "${MPC}/long_constraints/*.c")
    add_library(acados_ocp_solver_long SHARED ${MPC}/acados_solver_long.c ${MPC_FUNCTIONS})
    target_include_directories(acados_ocp_solver_long PUBLIC ${MPC} ${ACADOS_DEPS}/include
      ${ACADOS_DEPS}/include/blasfeo/include ${ACADOS_DEPS}/include/hpipm/include)
    target_link_libraries(acados_ocp_solver_long PUBLIC
      ${ACADOS_DEPS}/lib/libacados.so ${ACADOS_DEPS}/lib/libhpipm.so ${ACADOS_DEPS}/lib/libblasfeo.so m)
    add_library(acados_ocp_solver_pyx SHARED ${MPC}/acados_ocp_solver_pyx.c)
    target_link_libraries(acados_ocp_solver_pyx acados_ocp_solver_long)
    if(ANDROID)
      target_include_directories(acados_ocp_solver_pyx PRIVATE ${PYTHON_DEPS}/include/python3.12 ${PYTHON_DEPS}/numpy/_core/include)
      target_link_libraries(acados_ocp_solver_pyx ${PYTHON_DEPS}/jniLibs/${ANDROID_ABI}/libpython3.12.so)
    else()
      target_include_directories(acados_ocp_solver_pyx PRIVATE ${HOST_PYTHON_INCLUDE} ${HOST_NUMPY_INCLUDE})
    endif()
  endif()
endif()

file(GLOB MODEL_KERNELS CONFIGURE_DEPENDS "${REPO_ROOT}/tools/android/.cache/model-aot/kernels/*.c")
if(MODEL_KERNELS)
  add_library(openpilot_kernels SHARED ${MODEL_KERNELS})
  target_compile_options(openpilot_kernels PRIVATE -O2 -ffreestanding -fno-math-errno -ffp-contract=off)
  if(ANDROID)
    # ModelState aliases recurrent input/output views. Retained generated C
    # declares restrict on those arguments, which permits load/store reordering
    # that corrupts the image queue on ARM. Keep the model/source arithmetic;
    # remove the invalid pointer-alias promise for the Android implementation.
    target_compile_definitions(openpilot_kernels PRIVATE restrict=)
  endif()
  target_link_libraries(openpilot_kernels m)
endif()
