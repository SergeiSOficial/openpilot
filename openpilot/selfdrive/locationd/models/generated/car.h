#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_err_fun(double *nom_x, double *delta_x, double *out_1404578713789147457);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_4686486422632011807);
void car_H_mod_fun(double *state, double *out_580044127567052722);
void car_f_fun(double *state, double dt, double *out_2014789312445062039);
void car_F_fun(double *state, double dt, double *out_4432406039518459070);
void car_h_25(double *state, double *unused, double *out_4434722456094921626);
void car_H_25(double *state, double *unused, double *out_4323647697617612118);
void car_h_24(double *state, double *unused, double *out_2286200415919263266);
void car_H_24(double *state, double *unused, double *out_6500862121224762091);
void car_h_30(double *state, double *unused, double *out_797272927840899276);
void car_H_30(double *state, double *unused, double *out_6841980656124860745);
void car_h_26(double *state, double *unused, double *out_1807132392967798375);
void car_H_26(double *state, double *unused, double *out_582144378743555894);
void car_h_27(double *state, double *unused, double *out_6557551021466237620);
void car_H_27(double *state, double *unused, double *out_4667217344324435834);
void car_h_29(double *state, double *unused, double *out_4204400339819946369);
void car_H_29(double *state, double *unused, double *out_7352212000439252929);
void car_h_28(double *state, double *unused, double *out_8415018360440916746);
void car_H_28(double *state, double *unused, double *out_2269812983369722355);
void car_h_31(double *state, double *unused, double *out_7424193691138334827);
void car_H_31(double *state, double *unused, double *out_44063723489795582);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}