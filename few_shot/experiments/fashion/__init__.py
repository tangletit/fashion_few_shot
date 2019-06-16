import sys

import tensorflow as tf

from few_shot.dataset import FewShotEpisodeGenerator
from few_shot.dataset.image_pipeline import resize_img_pipeline_fn
from few_shot.model import build_embedding_model, build_prototype_network


def evaluate_fashion_few_shot(train_df,
                              val_df,
                              test_df,
                              lr,
                              n_shot,
                              n_queries_train,
                              n_queries_test,
                              k_way_train,
                              eps_per_epoch,
                              n_epochs,
                              k_way_test,
                              test_eps,
                              img_shape,
                              img_pipeline_fn=resize_img_pipeline_fn,
                              patience=1,
                              opt=None,
                              callbacks=None,
                              restore_best_weights=True):
    args = locals()
    args.pop('train_df')
    args.pop('test_df')
    args.pop('val_df')
    args.pop('img_pipeline_fn')
    args.pop('opt')
    args.pop('callbacks')

    train_dataset = FewShotEpisodeGenerator(train_df[['class_name', 'filepath']].copy(),
                                            n_epochs * eps_per_epoch,
                                            n_shot,
                                            k_way_train,
                                            n_queries_train)

    val_dataset = FewShotEpisodeGenerator(val_df[['class_name', 'filepath']].copy(),
                                          n_epochs * eps_per_epoch,
                                          n_shot,
                                          k_way_test,
                                          n_queries_test)

    test_dataset = FewShotEpisodeGenerator(test_df[['class_name', 'filepath']].copy(),
                                           n_epochs * eps_per_epoch,
                                           n_shot,
                                           k_way_test,
                                           n_queries_test)

    train_it = train_dataset.tf_iterator(image_pipeline=img_pipeline_fn(img_shape))
    val_it = val_dataset.tf_iterator(image_pipeline=img_pipeline_fn(img_shape))

    embedding_input = tf.keras.layers.Input(shape=img_shape)
    embedding_model = build_embedding_model(embedding_input)
    model = build_prototype_network(n_shot,
                                    k_way_train,
                                    n_queries_train,
                                    img_shape,
                                    embedding_model_fn=lambda x: embedding_model)

    if not opt:
        opt = tf.keras.optimizers.Adam(lr=lr)
    model.compile(optimizer=opt, loss='categorical_crossentropy', metrics=['categorical_accuracy'])

    if not callbacks:
        callbacks = [
                  tf.keras.callbacks.LearningRateScheduler(
                      lambda i, lr: lr if i % (2000//eps_per_epoch) else lr * 0.5)
              ]

    test_it = test_dataset.tf_iterator(image_pipeline=resize_img_pipeline_fn(img_shape))

    test_model = build_prototype_network(n_shot,
                                         k_way_test,
                                         n_queries_test,
                                         img_shape,
                                         embedding_model_fn=lambda x: embedding_model)
    test_opt = tf.keras.optimizers.Adam(lr=lr)
    test_model.compile(optimizer=test_opt, loss='categorical_crossentropy', metrics=['categorical_accuracy'])

    best_val_acc = 0.0
    best_val_loss = sys.float_info.max
    best_weights = model.get_weights()
    curr_step = 0  # for patience

    for i in range(n_epochs):
        model.fit(train_it,
                  epochs=1,
                  initial_epoch=i,
                  steps_per_epoch=eps_per_epoch,
                  shuffle=False)
        latest_weights = model.get_weights()

        val_loss, val_acc = test_model.evaluate(val_it, steps=eps_per_epoch)
        print(f'epoch {i}: val_loss: {val_loss}, val_cat_accuracy: {val_acc}')
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_weights = model.get_weights()
            curr_step = 0
        else:
            curr_step += 1

        if curr_step > patience:
            break
    if restore_best_weights:
        test_model.set_weights(best_weights)
        for a, b in zip(best_weights, test_model.get_weights()):
            assert (a == b).all()
    test_loss, test_acc = test_model.evaluate(test_it, steps=test_eps)
    args.update({
        'test_accuracy': test_acc,
        'test_loss': test_loss
    })
    return args
