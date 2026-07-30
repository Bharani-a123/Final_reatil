/*
 * SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from "react";
import { ApparelProps } from "../types";
import { getDefaultImage } from "../config/config";

const Apparel: React.FC<ApparelProps> = ({ newRenderImage, retrievedProducts = [], isCartView = false, onRemoveProduct, orderInfo }) => {
  const displayImage = newRenderImage || getDefaultImage();

  return (
    <div
      style={{ width: "40vw", padding: "24px", boxSizing: "border-box" }}
      className="flex flex-col bg-[#F9F9F9] border-r border-gray-200 h-[85vh] overflow-y-auto"
    >
      {orderInfo ? (
        <div className="flex flex-col w-[100%] gap-4">
          <h2 className="text-[20px] font-bold text-[#202020] mb-2 border-b pb-2 flex items-center justify-between">
            <span>📦 Order Details & Tracking</span>
            <span className="text-[14px] font-mono bg-blue-50 text-blue-600 px-2.5 py-0.5 rounded-full border border-blue-100 font-bold">
              {orderInfo.ref}
            </span>
          </h2>
          
          {/* Tracking Card */}
          <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 rounded-xl p-4 shadow-sm mb-2">
            <h3 className="text-[15px] font-bold text-[#1e3a8a] mb-2 flex items-center gap-1.5">
              <span>🚚</span> Shipping & Fulfillment Status
            </h3>
            <div className="grid grid-cols-1 gap-2 text-[13.5px] text-gray-700">
              <div className="flex justify-between border-b border-blue-100/50 pb-1.5">
                <span className="font-semibold text-gray-500">Order Reference:</span>
                <span className="font-mono font-bold text-gray-900">{orderInfo.ref}</span>
              </div>
              <div className="flex justify-between border-b border-blue-100/50 pb-1.5">
                <span className="font-semibold text-gray-500">Delivery Status:</span>
                <span className="font-bold text-[#10b981]">{orderInfo.status}</span>
              </div>
              <div className="flex justify-between border-b border-blue-100/50 pb-1.5">
                <span className="font-semibold text-gray-500">Carrier / Method:</span>
                <span className="font-medium text-gray-900">{orderInfo.carrier}</span>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="font-semibold text-gray-500">
                  {orderInfo.method === 'ship_to_home' ? 'Destination Address:' : 'Store Pickup Details:'}
                </span>
                <span className="text-gray-900 bg-white/70 p-2 rounded border border-blue-100/30 mt-1">
                  {orderInfo.method === 'ship_to_home' ? orderInfo.address : `${orderInfo.address} (Slot: ${orderInfo.slot})`}
                </span>
              </div>
            </div>
          </div>

          {/* Items Section */}
          <h3 className="text-[16px] font-bold text-[#202020] mt-2 mb-1">
            Ordered Items ({orderInfo.items?.length || 0})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {orderInfo.items?.map((product: any, idx: number) => (
              <div 
                key={idx} 
                className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col p-3 hover:shadow-md transition-all duration-200"
              >
                <div className="w-[100%] h-[180px] overflow-hidden rounded-md bg-gray-50 flex items-center justify-center mb-2 relative group">
                  <img
                    src={product.productUrl}
                    alt={product.productName}
                    className="max-h-[100%] max-w-[100%] object-contain transition-transform duration-300 group-hover:scale-105"
                    onError={(e) => {
                      (e.target as HTMLImageElement).src = getDefaultImage();
                    }}
                  />
                </div>
                <div className="text-[14px] font-bold text-[#202020] line-clamp-2 min-h-[40px] flex-grow">
                  {product.productName}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : retrievedProducts.length > 0 ? (
        <div className="flex flex-col w-[100%] gap-4">
          <h2 className="text-[20px] font-bold text-[#202020] mb-2 border-b pb-2 flex items-center justify-between">
            <span>{isCartView ? "Your Shopping Cart" : "Requested Catalog Items"}</span>
            {isCartView && (
              <span className="text-[14px] font-normal text-gray-500">
                ({retrievedProducts.length} {retrievedProducts.length === 1 ? "item" : "items"})
              </span>
            )}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {retrievedProducts.map((product, idx) => (
              <div 
                key={idx} 
                className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col p-3 hover:shadow-md transition-all duration-200"
              >
                <div className="w-[100%] h-[180px] overflow-hidden rounded-md bg-gray-50 flex items-center justify-center mb-2 relative group">
                  <img
                    src={product.productUrl}
                    alt={product.productName}
                    className="max-h-[100%] max-w-[100%] object-contain transition-transform duration-300 group-hover:scale-105"
                    onError={(e) => {
                      (e.target as HTMLImageElement).src = getDefaultImage();
                    }}
                  />
                </div>
                <div className="text-[14px] font-bold text-[#202020] line-clamp-2 min-h-[40px] flex-grow">
                  {product.productName}
                </div>
                {isCartView && onRemoveProduct && (
                  <button
                    onClick={() => onRemoveProduct(product.productName)}
                    className="mt-3 w-full py-2 bg-[#ff4d4f] hover:bg-[#e03d3e] text-white text-[13px] font-bold rounded-md transition-colors duration-200 flex items-center justify-center gap-1.5 shadow-sm active:scale-95 transform"
                  >
                    <span className="text-[14px]">🗑️</span> Remove Item
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex w-[100%] h-[100%] items-center justify-center overflow-hidden object-contain">
          <img
            src={displayImage}
            alt="Product display"
            className="product-image max-h-[100%] max-w-[100%] object-contain"
          />
        </div>
      )}
    </div>
  );
};

export default Apparel;
