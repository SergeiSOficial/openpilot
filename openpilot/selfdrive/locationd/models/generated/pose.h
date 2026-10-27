#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_7465916839184854202);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_1310847904861873779);
void pose_H_mod_fun(double *state, double *out_6607805894218821441);
void pose_f_fun(double *state, double dt, double *out_534660845839446436);
void pose_F_fun(double *state, double dt, double *out_384983850267682172);
void pose_h_4(double *state, double *unused, double *out_185862018060751764);
void pose_H_4(double *state, double *unused, double *out_9186464551296892708);
void pose_h_10(double *state, double *unused, double *out_4781947873589601556);
void pose_H_10(double *state, double *unused, double *out_8921185053970104970);
void pose_h_13(double *state, double *unused, double *out_4868669237854762150);
void pose_H_13(double *state, double *unused, double *out_6048005697080326107);
void pose_h_14(double *state, double *unused, double *out_9131403806369573347);
void pose_H_14(double *state, double *unused, double *out_6103676119001520412);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}