""" Training and testing of the model
"""

# Any amendments (including) to MOGOGNET below was made by: Byron Petselis, z5397993

import os
import copy
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
import torch
import torch.nn.functional as F
from models import init_model_dict, init_optim
from utils import one_hot_tensor, cal_sample_weight, gen_adj_mat_tensor, gen_test_adj_mat_tensor, cal_adj_mat_parameter
cuda = True if torch.cuda.is_available() else False

def split_csv_line_by_line(input_data_file, input_labels_file, test_size, train_size, output_folder, prefix):
    # Ensure the output directory exists
    os.makedirs(output_folder, exist_ok=True)

    # Define the output file paths using the prefix variable
    test_data_file = os.path.join(output_folder, f"{prefix}_te_split.csv")
    train_data_file = os.path.join(output_folder, f"{prefix}_tr_split.csv")
    test_labels_file = os.path.join(output_folder, f"labels_te_split.csv")
    train_labels_file = os.path.join(output_folder, f"labels_tr_split.csv")

    # Open the input files and output files
    with open(input_data_file, 'r') as data_in, \
         open(input_labels_file, 'r') as labels_in, \
         open(test_data_file, 'w') as test_data_out, \
         open(train_data_file, 'w') as train_data_out, \
         open(test_labels_file, 'w') as test_labels_out, \
         open(train_labels_file, 'w') as train_labels_out:
        
        # Write the header line to all output files
        data_header = data_in.readline()
        labels_header = labels_in.readline()
        test_data_out.write(data_header)
        train_data_out.write(data_header)
        test_labels_out.write(labels_header)
        train_labels_out.write(labels_header)

        # Process the rows line by line
        for idx, (data_row, labels_row) in enumerate(zip(data_in, labels_in)):
            if idx < test_size:
                # Write to test files
                test_data_out.write(data_row)
                test_labels_out.write(labels_row)
            elif idx < test_size + train_size:
                # Write to train files
                train_data_out.write(data_row)
                train_labels_out.write(labels_row)
            else:
                # Stop processing if the required number of rows has been written
                break

    print(f"Successfully created the following files:")
    print(f"  - Test data: {test_data_file}")
    print(f"  - Train data: {train_data_file}")
    print(f"  - Test labels: {test_labels_file}")
    print(f"  - Train labels: {train_labels_file}")

# Guide to prepare_trte_data, this is where the "database" would come in
# Instead of os.path... which gets file from computer, needs to be altered to get from database instead
# ------------------------------------------------------------------------------------------------------------------------
# labels_tr.csv: Training Labels
# labels_te.csv: Testing Labels
# 1_tr.csv: Training Data View 1
# 2_tr.csv: Training Data View 2
# 1_te.csv: Training Data View 1
# ------------------------------------------------------------------------------------------------------------------------
def prepare_trte_data(data_folder, view_list):
    num_view = len(view_list)
    # labels_tr = np.loadtxt(os.path.join(data_folder, "labels_tr.csv"), delimiter=',')
    # labels_te = np.loadtxt(os.path.join(data_folder, "labels_te.csv"), delimiter=',')
    labels_tr = np.loadtxt(os.path.join(data_folder, "labels_tr_split.csv"), delimiter=',')
    labels_te = np.loadtxt(os.path.join(data_folder, "labels_te_split.csv"), delimiter=',')
    labels_tr = labels_tr.astype(int)
    labels_te = labels_te.astype(int)
    data_tr_list = []
    data_te_list = []
    for i in view_list:
        # data_tr_list.append(np.loadtxt(os.path.join(data_folder, str(i)+"_tr.csv"), delimiter=','))
        # data_te_list.append(np.loadtxt(os.path.join(data_folder, str(i)+"_te.csv"), delimiter=','))
        data_tr_list.append(np.loadtxt(os.path.join(data_folder, str(i)+"_tr_split.csv"), delimiter=','))
        data_te_list.append(np.loadtxt(os.path.join(data_folder, str(i)+"_te_split.csv"), delimiter=','))
    num_tr = data_tr_list[0].shape[0]
    num_te = data_te_list[0].shape[0]
    data_mat_list = []
    for i in range(num_view):
        data_mat_list.append(np.concatenate((data_tr_list[i], data_te_list[i]), axis=0))
    data_tensor_list = []
    for i in range(len(data_mat_list)):
        data_tensor_list.append(torch.FloatTensor(data_mat_list[i]))
        if cuda:
            data_tensor_list[i] = data_tensor_list[i].cuda()
    idx_dict = {}
    idx_dict["tr"] = list(range(num_tr))
    idx_dict["te"] = list(range(num_tr, (num_tr+num_te)))
    data_train_list = []
    data_all_list = []
    for i in range(len(data_tensor_list)):
        data_train_list.append(data_tensor_list[i][idx_dict["tr"]].clone())
        data_all_list.append(torch.cat((data_tensor_list[i][idx_dict["tr"]].clone(),
                                       data_tensor_list[i][idx_dict["te"]].clone()),0))
    labels = np.concatenate((labels_tr, labels_te))
    
    return data_train_list, data_all_list, idx_dict, labels


def gen_trte_adj_mat(data_tr_list, data_trte_list, trte_idx, adj_parameter):
    adj_metric = "cosine" # cosine distance
    adj_train_list = []
    adj_test_list = []
    for i in range(len(data_tr_list)):
        adj_parameter_adaptive = cal_adj_mat_parameter(adj_parameter, data_tr_list[i], adj_metric)
        adj_train_list.append(gen_adj_mat_tensor(data_tr_list[i], adj_parameter_adaptive, adj_metric))
        adj_test_list.append(gen_test_adj_mat_tensor(data_trte_list[i], trte_idx, adj_parameter_adaptive, adj_metric))
    
    return adj_train_list, adj_test_list


def train_epoch(data_list, adj_list, label, one_hot_label, sample_weight, model_dict, optim_dict, train_VCDN=True):
    loss_dict = {}
    criterion = torch.nn.CrossEntropyLoss(reduction='none')
    for m in model_dict:
        model_dict[m].train()    
    num_view = len(data_list)
    for i in range(num_view):
        optim_dict["C{:}".format(i+1)].zero_grad()
        ci_loss = 0
        ci = model_dict["C{:}".format(i+1)](model_dict["E{:}".format(i+1)](data_list[i],adj_list[i]))
        ci_loss = torch.mean(torch.mul(criterion(ci, label),sample_weight))
        ci_loss.backward()
        optim_dict["C{:}".format(i+1)].step()
        loss_dict["C{:}".format(i+1)] = ci_loss.detach().cpu().numpy().item()
    if train_VCDN and num_view >= 2:
        optim_dict["C"].zero_grad()
        c_loss = 0
        ci_list = []
        for i in range(num_view):
            ci_list.append(model_dict["C{:}".format(i+1)](model_dict["E{:}".format(i+1)](data_list[i],adj_list[i])))
        c = model_dict["C"](ci_list)    
        c_loss = torch.mean(torch.mul(criterion(c, label),sample_weight))
        c_loss.backward()
        optim_dict["C"].step()
        loss_dict["C"] = c_loss.detach().cpu().numpy().item()
    
    return loss_dict
    

def test_epoch(data_list, adj_list, te_idx, model_dict):
    for m in model_dict:
        model_dict[m].eval()
    num_view = len(data_list)
    ci_list = []
    for i in range(num_view):
        ci_list.append(model_dict["C{:}".format(i+1)](model_dict["E{:}".format(i+1)](data_list[i],adj_list[i])))
    if num_view >= 2:
        c = model_dict["C"](ci_list)    
    else:
        c = ci_list[0]
    c = c[te_idx,:]
    prob = F.softmax(c, dim=1).data.cpu().numpy()
    
    return prob


def train_test(data_folder, view_list, num_class,
               lr_e_pretrain, lr_e, lr_c, 
               num_epoch_pretrain, num_epoch):
    test_inverval = 50
    num_view = len(view_list)
    dim_hvcdn = pow(num_class,num_view)
    if data_folder == 'ROSMAP':
        adj_parameter = 2
        dim_he_list = [200,200,100]
    if data_folder == 'BRCA':
        adj_parameter = 10
        dim_he_list = [400,400,200]
    data_tr_list, data_trte_list, trte_idx, labels_trte = prepare_trte_data(data_folder, view_list)
    labels_tr_tensor = torch.LongTensor(labels_trte[trte_idx["tr"]])
    onehot_labels_tr_tensor = one_hot_tensor(labels_tr_tensor, num_class)
    sample_weight_tr = cal_sample_weight(labels_trte[trte_idx["tr"]], num_class)
    sample_weight_tr = torch.FloatTensor(sample_weight_tr)
    if cuda:
        labels_tr_tensor = labels_tr_tensor.cuda()
        onehot_labels_tr_tensor = onehot_labels_tr_tensor.cuda()
        sample_weight_tr = sample_weight_tr.cuda()
    adj_tr_list, adj_te_list = gen_trte_adj_mat(data_tr_list, data_trte_list, trte_idx, adj_parameter)
    dim_list = [x.shape[1] for x in data_tr_list]
    model_dict = init_model_dict(num_view, num_class, dim_list, dim_he_list, dim_hvcdn)
    for m in model_dict:
        if cuda:
            model_dict[m].cuda()
    
    print("\nPretrain GCNs...")
    optim_dict = init_optim(num_view, model_dict, lr_e_pretrain, lr_c)
    for epoch in range(num_epoch_pretrain):
        train_epoch(data_tr_list, adj_tr_list, labels_tr_tensor, 
                    onehot_labels_tr_tensor, sample_weight_tr, model_dict, optim_dict, train_VCDN=False)
    print("\nTraining...")
    optim_dict = init_optim(num_view, model_dict, lr_e, lr_c)
    for epoch in range(num_epoch+1):
        train_epoch(data_tr_list, adj_tr_list, labels_tr_tensor, 
                    onehot_labels_tr_tensor, sample_weight_tr, model_dict, optim_dict)
        if epoch % test_inverval == 0:
            # te_prob = test_epoch(data_trte_list, adj_te_list, trte_idx["te"], model_dict)
            te_prob = test_epoch(data_trte_list, adj_te_list, trte_idx["te"], model_dict)

            # This is where the data for the visualisation comes in
            # If done correctly, below section will produce 3 graphs
            # Each Epoch add 3 distinct points to it's respective curves
            # ------------------------------------------------------------------------------------------------------------------------
            # Test ACC: Plots for accuracy curve, each epoch adds the next point
            # ------------------------------------------------------------------------------------------------------------------------

            print("\nTest: Epoch {:d}".format(epoch))
            if num_class == 2:
                print("Test ACC: {:.3f}".format(accuracy_score(labels_trte[trte_idx["te"]], te_prob.argmax(1))))
                print("Test F1: {:.3f}".format(f1_score(labels_trte[trte_idx["te"]], te_prob.argmax(1))))
                print("Test AUC: {:.3f}".format(roc_auc_score(labels_trte[trte_idx["te"]], te_prob[:,1])))
            else:
                print("Test ACC: {:.3f}".format(accuracy_score(labels_trte[trte_idx["te"]], te_prob.argmax(1))))
                print("Test F1 weighted: {:.3f}".format(f1_score(labels_trte[trte_idx["te"]], te_prob.argmax(1), average='weighted')))
                print("Test F1 macro: {:.3f}".format(f1_score(labels_trte[trte_idx["te"]], te_prob.argmax(1), average='macro')))
            print()

            print(f"Predictions: {te_prob.argmax(1)}\n")

    featimp_list = cal_feat_imp(data_folder, model_dict, view_list, num_class)
    summarize_imp_feat(featimp_list)

# Guide to cal_feat_imp, this is where the "database" would come in again
# Instead of os.path... which gets file from computer, needs to be altered to get from database instead
# ------------------------------------------------------------------------------------------------------------------------
# 1_featname.csv: feature names View 1
# ------------------------------------------------------------------------------------------------------------------------
def cal_feat_imp(data_folder, model_dict, view_list, num_class):
    num_view = len(view_list)
    dim_hvcdn = pow(num_class,num_view)
    if data_folder == 'ROSMAP':
        adj_parameter = 2
        dim_he_list = [200,200,100]
    if data_folder == 'BRCA':
        adj_parameter = 10
        dim_he_list = [400,400,200]
    data_tr_list, data_trte_list, trte_idx, labels_trte = prepare_trte_data(data_folder, view_list)
    adj_tr_list, adj_te_list = gen_trte_adj_mat(data_tr_list, data_trte_list, trte_idx, adj_parameter)
    featname_list = []
    for v in view_list:
        df = pd.read_csv(os.path.join(data_folder, str(v)+"_featname.csv"), header=None)
        featname_list.append(df.values.flatten())
    
    dim_list = [x.shape[1] for x in data_tr_list]

    # model_dict = init_model_dict(num_view, num_class, dim_list, dim_he_list, dim_hvcdn)
    # for m in model_dict:
    #     if cuda:
    #         model_dict[m].cuda()
    # model_dict = load_model_dict(model_folder, model_dict)
    
    te_prob = test_epoch(data_trte_list, adj_te_list, trte_idx["te"], model_dict)
    if num_class == 2:
        f1 = f1_score(labels_trte[trte_idx["te"]], te_prob.argmax(1))
    else:
        f1 = f1_score(labels_trte[trte_idx["te"]], te_prob.argmax(1), average='macro')
    
    feat_imp_list = []
    for i in range(len(featname_list)):
        feat_imp = {"feat_name":featname_list[i]}
        feat_imp['imp'] = np.zeros(dim_list[i])
        for j in range(dim_list[i]):
            feat_tr = data_tr_list[i][:,j].clone()
            feat_trte = data_trte_list[i][:,j].clone()
            data_tr_list[i][:,j] = 0
            data_trte_list[i][:,j] = 0
            adj_tr_list, adj_te_list = gen_trte_adj_mat(data_tr_list, data_trte_list, trte_idx, adj_parameter)
            te_prob = test_epoch(data_trte_list, adj_te_list, trte_idx["te"], model_dict)
            if num_class == 2:
                f1_tmp = f1_score(labels_trte[trte_idx["te"]], te_prob.argmax(1))
            else:
                f1_tmp = f1_score(labels_trte[trte_idx["te"]], te_prob.argmax(1), average='macro')
            feat_imp['imp'][j] = (f1-f1_tmp)*dim_list[i]
            
            data_tr_list[i][:,j] = feat_tr.clone()
            data_trte_list[i][:,j] = feat_trte.clone()
        feat_imp_list.append(pd.DataFrame(data=feat_imp))
    
    return feat_imp_list

def summarize_imp_feat(featimp_list, topn=30):
    """
    Summarizes feature importance from a list of DataFrames and prints the top N features.
    
    Args:
    - featimp_list: A list of DataFrames where each DataFrame contains feature importance scores.
    - topn: The number of top features to display. Default is 30.
    
    Returns:
    - df_featimp_top: DataFrame containing the top N features sorted by importance.
    """
    
    num_view = len(featimp_list)  # Number of views (i.e., datasets or modalities)
    df_tmp_list = []
    
    # Iterate through each view in the list
    for v in range(num_view):
        df_tmp = copy.deepcopy(featimp_list[v])  # Deep copy to avoid modifying the original DataFrame
        df_tmp['omics'] = np.ones(df_tmp.shape[0], dtype=int) * v  # Add 'omics' column for view tracking
        df_tmp_list.append(df_tmp.copy(deep=True))  # Append the modified DataFrame
    
    # Concatenate all DataFrames into a single DataFrame
    df_featimp = pd.concat(df_tmp_list).copy(deep=True)
    
    # Group by 'feat_name' and 'omics', summing the 'imp' (importance) values
    df_featimp_top = df_featimp.groupby(['feat_name', 'omics'])['imp'].sum().reset_index()
    
    # Sort the DataFrame by importance (descending)
    df_featimp_top = df_featimp_top.sort_values(by='imp', ascending=False)
    
    # Select the top N features
    df_featimp_top = df_featimp_top.iloc[:topn]
    
    # Print the top N features and their rankings
    print('{:}\t{:}'.format('Rank', 'Feature name'))
    for i in range(len(df_featimp_top)):
        print('{:}\t{:}'.format(i + 1, df_featimp_top.iloc[i]['feat_name']))
    
    return df_featimp_top  # Optionally return the top N features as a DataFrame
